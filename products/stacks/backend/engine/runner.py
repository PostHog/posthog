from __future__ import annotations

import os
import json
import shutil
import signal
import hashlib
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import current_thread, main_thread
from time import monotonic
from types import FrameType
from typing import Any
from urllib.parse import urlsplit

from .addresses import EVENT_LINK, address, decode_address
from .check_imports import check_imports
from .claims import check_saved_claims, entity_id_key, saved_adoptions
from .deadline import DEFAULT_TIMEOUT_SECONDS, remaining
from .event_imports import event_imports, membership_moves
from .mappings import load_mapping
from .natural_keys import check_import_identities, natural_imports
from .record_backend import RecordDelivery, record_backend
from .translate_out import STACK_INTERRUPTED_MESSAGE, translate_error, translate_out
from .types import BindingRecord, Credentials, Diff, DiffError, EngineError, EngineInput, EngineOptions, PushResult


def _error(code: str, message: str) -> EngineError:
    return EngineError([{"code": code, "message": message}])


def _snapshot(state_bytes: bytes | None) -> dict[str, Any]:
    if not state_bytes:
        return {"serial": 0, "resources": []}
    try:
        data = json.loads(state_bytes)
        if isinstance(data, dict) and type(data["serial"]) is int and isinstance(data["resources"], list):
            return data
    except (ValueError, KeyError):
        pass
    raise _error("snapshot_invalid", "Restore the last saved stack snapshot and run diff again.")


def _instance_address(resource: Mapping[str, Any], instance: Mapping[str, Any]) -> str:
    name = f"{resource['type']}.{resource['name']}"
    if "index_key" in instance:
        name += "[" + json.dumps(instance["index_key"], ensure_ascii=False) + "]"
    return name


def _instances(snapshot: Mapping[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    try:
        for resource in snapshot["resources"]:
            if resource.get("mode") != "managed" or resource.get("module"):
                continue
            for instance in resource["instances"]:
                if instance.get("deposed"):
                    continue
                if not isinstance(instance.get("attributes"), dict):
                    raise ValueError
                yield _instance_address(resource, instance), instance
    except (AttributeError, KeyError, ValueError, TypeError):
        raise _error("snapshot_invalid", "Restore the last saved stack snapshot and run diff again.") from None


def read_bindings(state_bytes: bytes) -> list[BindingRecord]:
    bindings: list[BindingRecord] = []
    for name, instance in _instances(_snapshot(state_bytes)):
        identity = decode_address(name)
        if identity and not identity[2]:
            entity_id = instance["attributes"].get("id")
            if isinstance(entity_id, (str, int)) and not isinstance(entity_id, bool):
                bindings.append({"kind": identity[0], "key": identity[1], "entity_id": entity_id})
    return sorted(bindings, key=lambda binding: (binding["kind"], binding["key"]))


def _target(engine_input: EngineInput, credentials: Credentials) -> dict[str, str]:
    description = json.dumps(engine_input.description, sort_keys=True, separators=(",", ":")).encode()
    return {
        "host": credentials["host"].rstrip("/"),
        "project": str(credentials["project_id"]),
        "description": hashlib.sha256(description).hexdigest(),
    }


def _validate_credentials(credentials: Credentials) -> None:
    if not credentials.get("api_key"):
        raise EngineError(translate_error("Missing API key"))
    try:
        host = urlsplit(credentials["host"])
        if (
            host.scheme in {"http", "https"}
            and host.hostname
            and host.username is None
            and host.password is None
            and not host.query
            and not host.fragment
            and str(credentials["project_id"]).isascii()
            and str(credentials["project_id"]).isdigit()
        ):
            return
    except ValueError:
        pass
    raise _error("target_invalid", "Check the project ID and host, then run diff again.")


def _binary(options: EngineOptions) -> str:
    executable = shutil.which(str(options.get("binary", "tofu")))
    if not executable:
        raise _error("runner_unavailable", "Check the stack worker installation and try again.")
    return str(Path(executable).resolve())


def _cli_config(options: EngineOptions) -> str:
    mirror = options.get("mirror")
    if mirror:
        path = Path(mirror).resolve()
        if not path.is_dir():
            raise _error("mirror_missing", "Choose an installed stack mirror and try again.")
        return "provider_installation {\n  filesystem_mirror {\n    path = " + json.dumps(str(path)) + "\n  }\n}\n"
    if options.get("allow_registry") is True:
        return "provider_installation {\n  direct {}\n}\n"
    raise _error("mirror_missing", "Choose an installed stack mirror or use --allow-registry on a development machine.")


@contextmanager
def _cleanup_on_termination() -> Iterator[None]:
    if current_thread() is not main_thread() or signal.getsignal(signal.SIGTERM) != signal.SIG_DFL:
        yield
        return

    terminated = False

    def terminate(signum: int, frame: FrameType | None) -> None:
        nonlocal terminated
        terminated = True
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        if terminated:
            # Keep the supervisor's signal exit status after the private directory and its children are gone.
            signal.raise_signal(signal.SIGTERM)


@contextmanager
def _workspace(
    workdir: str | Path,
    engine_input: EngineInput,
    state_bytes: bytes | None,
    credentials: Credentials,
    extra_imports: list[dict[str, str]] | None = None,
    *,
    on_write: Callable[[bytes], None] | None = None,
) -> Iterator[tuple[Path, dict[str, str]]]:
    cli_config = _cli_config(engine_input.options)
    Path(workdir).mkdir(parents=True, exist_ok=True)
    with _cleanup_on_termination(), TemporaryDirectory(prefix="stack-", dir=workdir) as tmp:
        directory = Path(tmp).resolve()
        cli = directory / "cli.tfrc"
        cli.write_text(cli_config)
        config = dict(engine_input.config)
        config["terraform"] = {**config.get("terraform", {}), "backend": {"http": {}}}
        config["variable"] = {
            **config.get("variable", {}),
            "stack_run_target": {"type": "map(string)"},
            "stack_project_id": {"type": "string"},
        }
        if extra_imports:
            config["import"] = [*config.get("import", []), *extra_imports]
        (directory / "main.tf.json").write_text(json.dumps(config))
        if state_bytes:
            (directory / "stack.record").write_bytes(state_bytes)
        env = {
            "PATH": os.defpath,
            "HOME": str(directory),
            "TF_CLI_CONFIG_FILE": str(cli),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "CHECKPOINT_DISABLE": "1",
            "POSTHOG_HOST": credentials["host"],
            "POSTHOG_PROJECT_ID": str(credentials["project_id"]),
            "TF_VAR_stack_project_id": str(credentials["project_id"]),
            "POSTHOG_API_KEY": credentials["api_key"],
        }
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "TMPDIR"):
            if name in os.environ:
                env[name] = os.environ[name]
        with record_backend(directory / "stack.record", read_bindings, on_write) as backend_env:
            yield directory, {**env, **backend_env}


def _command(
    binary: str,
    directory: Path,
    env: Mapping[str, str],
    deadline: float,
    *args: str,
    delivery: RecordDelivery | None = None,
    secret_values: tuple[str, ...] = (),
) -> bytes:
    remaining(deadline)
    try:
        process = subprocess.Popen(
            [binary, *args],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        raise _error("runner_unavailable", "Check the stack worker installation and try again.") from None

    def stop() -> None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)

    with process:
        try:
            with delivery.stop_on_abort(stop) if delivery is not None else nullcontext():
                while True:
                    # poll(2) takes a signed millisecond count. Long runs use multiple waits against the same deadline.
                    with suppress(subprocess.TimeoutExpired):
                        stdout, stderr = process.communicate(timeout=min(remaining(deadline), 86_400))
                        break
        except BaseException:
            # Plugins can outlive the binary and keep its pipes and private files open.
            stop()
            process.wait()
            raise
    if process.returncode < 0:
        # Killed by a signal: a write may have reached PostHog without the record saying so.
        raise _error("stack_interrupted", STACK_INTERRUPTED_MESSAGE)
    if process.returncode:
        diagnostics = translate_error(stdout, secret_values=secret_values) if "-json" in args else []
        raise EngineError(
            diagnostics or translate_error(stderr or stdout or b"Command failed", secret_values=secret_values)
        )
    return stdout


def _init(binary: str, directory: Path, env: Mapping[str, str], deadline: float) -> None:
    _command(binary, directory, env, deadline, "init", "-input=false", "-no-color")


def _show(binary: str, directory: Path, env: Mapping[str, str], deadline: float) -> dict[str, Any]:
    return json.loads(_command(binary, directory, env, deadline, "show", "-json", "saved.diff"))


def _release_unconfigured(engine_input: EngineInput, occupied: set[str]) -> EngineInput:
    # An older snapshot can predate the binding index. Removing a definition also removes its prevent_destroy guard.
    config = engine_input.config
    configured = {f"{kind}.{label}" for kind, resources in config.get("resource", {}).items() for label in resources}
    handled = configured | {block["from"] for block in config.get("removed", []) + config.get("moved", [])}
    releases = [
        {"from": name, "lifecycle": {"destroy": False}}
        for name in sorted(occupied - handled)
        if (identity := decode_address(name))
        and load_mapping(identity[0])["removal"] == "prevent"
        and not (name.startswith(EVENT_LINK + ".") and address("event", identity[1]) in configured)
    ]
    if not releases:
        return engine_input
    return replace(engine_input, config={**config, "removed": [*config.get("removed", []), *releases]})


def _check_saved_removals(saved: dict[str, Any], adopted_ids: set[tuple[str, str]], released: set[str]) -> None:
    for row in saved.get("resource_changes", ()):
        change = row["change"]
        if "delete" not in change["actions"] or not (identity := decode_address(row["address"])):
            continue
        kind, key, _ = identity
        if (
            row["address"].startswith(EVENT_LINK + ".")
            and address("event", key) not in released
            and row["address"] not in released
        ):
            # Removing one membership edits a managed event; removing the event releases all its memberships.
            continue
        entity_id = (change.get("before") or {}).get("id")
        if (
            row["address"] in released
            or load_mapping(kind)["removal"] == "prevent"
            or (entity_id is not None and (kind, entity_id_key(kind, entity_id)) in adopted_ids)
        ):
            raise EngineError(
                [
                    {
                        "code": "removal_blocked",
                        "message": "This saved diff would delete a protected entity. Run diff again to review its binding.",
                        "kind": kind,
                        "key": key,
                    }
                ]
            )


def _plan(
    binary: str,
    directory: Path,
    env: Mapping[str, str],
    deadline: float,
    variables: dict[str, dict[str, str]],
    refresh: bool,
    secret_values: tuple[str, ...],
) -> dict[str, Any]:
    # JSON variable files keep template markers in secret values literal. TF_VAR map values parse them as expressions.
    inputs = directory / "inputs.auto.tfvars.json"
    inputs.write_text(json.dumps(variables))
    try:
        _command(
            binary,
            directory,
            env,
            deadline,
            "plan",
            "-json",
            "-input=false",
            f"-refresh={str(refresh).lower()}",
            "-out=saved.diff",
            secret_values=secret_values,
        )
    finally:
        inputs.unlink(missing_ok=True)
    return _show(binary, directory, env, deadline)


def _missing_entities(plan: dict[str, Any], moves: dict[str, str]) -> dict[str, dict[str, Any]]:
    creates = {row["address"] for row in plan.get("resource_changes", []) if row["change"]["actions"] == ["create"]}
    missing = {}
    for row in plan.get("resource_drift", []):
        target = moves.get(row["address"], row["address"])
        if target in creates and row["change"]["actions"] == ["delete"]:
            missing[target] = row
    return missing


def _stage_discovered_bindings(
    directory: Path,
    snapshot: dict[str, Any],
    moves: dict[str, str],
    missing: dict[str, dict[str, Any]],
    imports: list[dict[str, str]],
    link_moves: list[dict[str, str]],
) -> list[dict[str, Any]]:
    # OpenTofu ignores an import when its address was occupied before refresh, even when refresh found the entity gone.
    # Remove only confirmed deletions from this private copy. The original serial and lineage still guard the saved diff at push.
    replacements = missing.keys() & {block["to"] for block in imports}
    resources = []
    for resource in snapshot["resources"]:
        if resource.get("module") or resource.get("mode") != "managed":
            resources.append(resource)
            continue
        kept = []
        for instance in resource["instances"]:
            old = _instance_address(resource, instance)
            target = moves.get(old, old)
            if target in replacements and not instance.get("deposed"):
                before = missing[target]["change"]["before"]
                if str(instance["attributes"]["id"]) == str(before["id"]):
                    continue
            kept.append(instance)
        if kept or not resource["instances"]:
            resources.append({**resource, "instances": kept})
    if replacements:
        (directory / "stack.record").write_text(json.dumps({**snapshot, "resources": resources}))
    config_file = directory / "main.tf.json"
    config = json.loads(config_file.read_bytes())
    if link_moves:
        config.setdefault("moved", []).extend(link_moves)
    by_target = {block["to"]: block for block in config.get("import", [])}
    by_target.update((block["to"], block) for block in imports)
    config["import"] = list(by_target.values())
    check_import_identities(config["import"])
    config_file.write_text(json.dumps(config))
    return [{**missing[target], "address": target} for target in sorted(replacements)]


def _verify_import_ids(plan: dict[str, Any], expected: dict[str, str | int]) -> None:
    for row in plan.get("resource_changes", ()):
        name = row["address"]
        if name not in expected or not (identity := decode_address(name)):
            continue
        change = row["change"]
        actual = (change.get("before") or {}).get("id") or (change.get("after") or {}).get("id")
        if actual is None or entity_id_key(identity[0], actual) != entity_id_key(identity[0], expected[name]):
            raise EngineError(
                [
                    {
                        "code": "binding_conflict",
                        "message": "The entity selected for adoption changed. Check its binding and run diff again.",
                        "kind": identity[0],
                        "key": identity[1],
                    }
                ]
            )


def _planned_ids(plan: dict[str, Any]) -> dict[str, str | int]:
    ids = {}
    for row in plan.get("resource_changes", ()):
        target, change = row["address"], row["change"]
        values = change.get("after")
        if target.startswith(EVENT_LINK + ".") and change.get("before"):
            # A link scheduled for deletion still owns its ID until the push finishes.
            values = change["before"]
        if values and isinstance(values.get("id"), (int, str)):
            ids[target] = values["id"]
    return ids


def _check_new_upserts(
    saved: dict[str, Any], engine_input: EngineInput, credentials: Credentials, deadline: float
) -> None:
    # A name can become occupied after review. A create that now upserts would write to an unreviewed entity.
    targets = {
        row["address"]
        for row in saved.get("resource_changes", ())
        if row["change"]["actions"] == ["create"]
        and (identity := decode_address(row["address"]))
        and not identity[2]
        and identity[0] in {"event", "model", "context_page"}
    }
    if targets and natural_imports(engine_input, set(), credentials, deadline=deadline, recheck=targets):
        raise _error("stack_moved", "An entity now matches this definition. Run diff again and review its adoption.")
    held = {row["address"] for row in saved.get("resource_changes", ()) if row["change"]["actions"] != ["create"]}
    if check_imports(engine_input, held, _planned_ids(saved), credentials, deadline):
        raise _error("stack_moved", "An entity now matches this definition. Run diff again and review its adoption.")


def run_diff(
    workdir: str | Path, engine_input: EngineInput, state_bytes: bytes | None, credentials: Credentials
) -> tuple[Diff, bytes, int]:
    serial = 0
    deadline = monotonic() + engine_input.options.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        snapshot = _snapshot(state_bytes)
        serial = snapshot["serial"]
        _validate_credentials(credentials)
        secrets = credentials.get("secrets", {})
        secret_values = (credentials["api_key"], *secrets.values())
        missing_secrets = sorted(engine_input.secret_names - secrets.keys())
        if missing_secrets:
            raise EngineError(
                [
                    {
                        "code": "secret_missing",
                        "message": f"Add the named secret {name} to this stack and run diff again.",
                    }
                    for name in missing_secrets
                ]
            )
        binary = _binary(engine_input.options)
        occupied = {name for name, _ in _instances(snapshot)}
        moves = {block["from"]: block["to"] for block in engine_input.config.get("moved", [])}
        expected_ids = dict(engine_input.import_entity_ids)
        engine_input = _release_unconfigured(engine_input, occupied)
        imports = natural_imports(engine_input, occupied, credentials, deadline=deadline, found_ids=expected_ids)
        with _workspace(workdir, engine_input, state_bytes, credentials, imports) as (directory, env):
            variables: dict[str, dict[str, str]] = {"stack_run_target": _target(engine_input, credentials)}
            if engine_input.secret_names:
                variables["stack_secrets"] = {name: secrets[name] for name in sorted(engine_input.secret_names)}
            _init(binary, directory, env, deadline)
            refresh = engine_input.options.get("refresh", True)
            plan = _plan(binary, directory, env, deadline, variables, refresh, secret_values)
            missing = _missing_entities(plan, moves)
            discovered: list[dict[str, str]] = []
            if missing:
                discovered = natural_imports(
                    engine_input, occupied, credentials, deadline=deadline, recheck=set(missing), found_ids=expected_ids
                )
            known_ids = {**_planned_ids(plan), **expected_ids}
            held = {
                row["address"] for row in plan.get("resource_changes", ()) if row["change"]["actions"] != ["create"]
            }
            link_moves = membership_moves(plan)
            held.update(move["to"] for move in link_moves)
            discovered.extend(event_imports(engine_input, held, known_ids, credentials, deadline))
            checks = check_imports(engine_input, held, known_ids, credentials, deadline)
            expected_ids.update({block["to"]: block["id"] for block in checks})
            discovered.extend(checks)
            if discovered or link_moves:
                deleted = _stage_discovered_bindings(directory, snapshot, moves, missing, discovered, link_moves)
                plan = _plan(binary, directory, env, deadline, variables, refresh, secret_values)
                adopted = {row["address"] for row in plan.get("resource_changes", ()) if row["change"].get("importing")}
                if any(block["to"] not in adopted for block in discovered):
                    raise _error("binding_conflict", "Choose the entity to adopt and run diff again.")
                plan["resource_drift"] = [*plan.get("resource_drift", []), *deleted]
            _verify_import_ids(plan, expected_ids)
            check_saved_claims(plan, engine_input.options.get("claimed", []))
            diff = translate_out(plan, engine_input.description, secret_values=secret_values)
            return diff, b"" if diff["errors"] else (directory / "saved.diff").read_bytes(), serial
    except EngineError as exc:
        diff = translate_out({}, engine_input.description)
        diff["errors"] = exc.errors
        return diff, b"", serial


def run_push(
    workdir: str | Path,
    engine_input: EngineInput,
    saved_plan_bytes: bytes,
    state_bytes: bytes | None,
    credentials: Credentials,
    *,
    on_record: Callable[[bytes], None] | None = None,
) -> tuple[PushResult, bytes]:
    new_state = state_bytes or b""
    adopted_ids = set(engine_input.adopted_ids)
    deadline = monotonic() + engine_input.options.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    errors: list[DiffError] = []
    delivery = RecordDelivery(on_record)

    try:
        _snapshot(state_bytes)
        _validate_credentials(credentials)
        binary = _binary(engine_input.options)
        with _workspace(workdir, engine_input, state_bytes, credentials, on_write=delivery.publish) as (directory, env):
            (directory / "saved.diff").write_bytes(saved_plan_bytes)
            _init(binary, directory, env, deadline)
            saved = _show(binary, directory, env, deadline)
            if saved.get("variables", {}).get("stack_run_target", {}).get("value") != _target(
                engine_input, credentials
            ):
                raise _error("stack_moved", "The saved diff belongs to another stack or definition. Run diff again.")
            check_saved_claims(saved, engine_input.options.get("claimed", []))
            _check_new_upserts(saved, engine_input, credentials, deadline)
            adopted_ids.update((kind, entity_id_key(kind, entity_id)) for kind, _, entity_id in saved_adoptions(saved))
            _check_saved_removals(
                saved, adopted_ids, {block["from"] for block in engine_input.config.get("removed", [])}
            )
            if state_bytes:
                # Older saved plans select the local backend. Seed its file after init so it cannot trigger backend migration.
                (directory / "terraform.tfstate").write_bytes(state_bytes)
            try:
                # A lease check at a checkpoint must finish before another resource can start writing to PostHog.
                concurrency = ["-parallelism=1"] if on_record is not None else []
                _command(
                    binary,
                    directory,
                    env,
                    deadline,
                    "apply",
                    "-json",
                    "-input=false",
                    *concurrency,
                    "saved.diff",
                    delivery=delivery,
                    secret_values=(credentials["api_key"], *credentials.get("secrets", {}).values()),
                )
            finally:
                # A failed push can still create entities. Keep their bindings so a retry sees them.
                checkpoints = ["stack.record"] if delivery.last_record is not None else []
                for filename in ("errored.tfstate", *checkpoints, "terraform.tfstate", "terraform.tfstate.backup"):
                    path = directory / filename
                    try:
                        candidate = path.read_bytes()
                        if not candidate:
                            raise ValueError
                        read_bindings(candidate)
                    except FileNotFoundError:
                        continue
                    except (OSError, ValueError):
                        errors = _error(
                            "snapshot_invalid", "Restore the last saved stack snapshot and run diff again."
                        ).errors
                        continue
                    new_state = candidate
                    break
    except EngineError as exc:
        errors = exc.errors
    try:
        bindings = read_bindings(new_state)
        for binding in bindings:
            kind = binding["kind"]
            if (kind, entity_id_key(kind, binding["entity_id"])) in adopted_ids:
                binding["origin"] = "adopted"
        if new_state and on_record is not None:
            if new_state != state_bytes and new_state != delivery.last_record:
                # A local recovery file can contain a write that never reached the HTTP backend.
                delivery.publish(new_state)
            delivery.publish(new_state)
    except EngineError as exc:
        bindings = []
        errors = errors or exc.errors
    delivery.raise_if_failed()
    return {"errors": errors, "bindings": bindings}, new_state
