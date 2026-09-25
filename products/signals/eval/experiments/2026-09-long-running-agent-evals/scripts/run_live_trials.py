from __future__ import annotations

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import UTC, datetime
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "skipped"}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
        raise RuntimeError("The API redirected the request. Use its canonical host.")


class TrialHTTPError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {detail}")


class TrialClient:
    def __init__(self, host: str, token: str) -> None:
        parsed = urlparse(host)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("Use HTTPS, or HTTP on localhost for development.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("The host must not contain credentials, a query, or a fragment.")
        self.host = host.rstrip("/")
        self.token = token

    def request(self, path: str, body: dict[str, Json] | None = None) -> dict[str, Json]:
        payload = self.read_json(path, body)
        if not isinstance(payload, dict):
            raise ValueError("The scout API returned an unexpected response.")
        return payload

    def read_json(self, path: str, body: dict[str, Json] | None = None) -> Json:
        request = Request(
            f"{self.host}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        for attempt in range(4):
            try:
                with build_opener(NoRedirects()).open(request, timeout=45) as response:
                    payload = json.load(response)
                return payload
            except HTTPError as error:
                if error.code < 500 and error.code != 429:
                    detail = error.read().decode(errors="replace")[:2000]
                    raise TrialHTTPError(error.code, detail) from error
                if attempt == 3:
                    raise RuntimeError(
                        f"HTTP {error.code}; retry this saved manifest to keep launch identities."
                    ) from error
            except (TimeoutError, URLError, RemoteDisconnected, IncompleteRead) as error:
                if attempt == 3:
                    raise RuntimeError("The API did not respond; retry this saved manifest.") from error
            time.sleep(2**attempt)
        raise RuntimeError("The API request could not complete.")


def save_json(path: Path, value: Json) -> None:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(value, indent=2) + "\n")
            stream.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def private_output_directory(path: Path) -> Path:
    output = path.resolve()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if output.is_relative_to(root):
        check = subprocess.run(["git", "check-ignore", "--quiet", str(output / "manifest.json")], check=False)
        if check.returncode:
            raise ValueError("Save trial data outside the repository or in a gitignored directory such as playground/.")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.stat().st_mode & 0o077:
        raise ValueError("The output directory must be private. Set its permissions to 700 or choose a new directory.")
    return output


class Comparison:
    def __init__(self, client: TrialClient, output: Path, manifest: dict[str, Json]) -> None:
        self.client = client
        self.output = output
        self.manifest = manifest
        self.base = f"/api/projects/{manifest['project_id']}/signals/scout/configs/{manifest['config_id']}/"

    def save(self) -> None:
        save_json(self.output / "manifest.json", self.manifest)

    def download_logs(self, result: dict[str, Json], launch_id: str) -> None:
        if not result.get("task_id") or not result.get("task_run_id"):
            return
        base = f"/api/projects/{self.manifest['project_id']}/tasks/{result['task_id']}/runs/{result['task_run_id']}/session_logs/"
        entries: list[Json] = []
        while True:
            page = self.client.read_json(f"{base}?limit=500&offset={len(entries)}")
            if not isinstance(page, list):
                raise ValueError("The session logs API returned an unexpected response.")
            if not page:
                break
            entries.extend(page)
        save_json(self.output / f"{launch_id}.session-log.json", entries)

    def run(self, concurrency: int, timeout: int) -> None:
        runs = self.manifest["runs"]
        if not isinstance(runs, list) or not all(isinstance(row, dict) for row in runs):
            raise ValueError("The manifest has no valid run list.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            active = sum(isinstance(row, dict) and row.get("status") == "running" for row in runs)
            for row in runs:
                if time.monotonic() >= deadline:
                    break
                if not isinstance(row, dict) or row.get("status") == "done":
                    continue
                body = row.get("request")
                if not isinstance(body, dict):
                    raise ValueError("A manifest run has no saved request.")
                if row.get("status") != "running":
                    if active >= concurrency:
                        continue
                    if self.manifest.get("context_id") and "context_id" not in body and "started" not in row:
                        body["context_id"] = self.manifest["context_id"]
                    # Save retry identity and exact input before an ambiguous network failure can occur.
                    self.save()
                    started = self.client.request(f"{self.base}trial/", body)
                    self.manifest["context_id"] = started["context_id"]
                    row["started"] = started
                    row["status"] = "running"
                    active += 1
                    self.save()
                query = urlencode({"launch_id": str(body["launch_id"])})
                result = self.client.request(f"{self.base}trial_result/?{query}")
                row["last_status"] = result["status"]
                if result["status"] == "not_started":
                    row["status"] = "pending"
                    active -= 1
                if result["status"] in TERMINAL_STATUSES:
                    launch_id = str(body["launch_id"])
                    save_json(self.output / f"{launch_id}.result.json", result)
                    try:
                        self.download_logs(result, launch_id)
                    except TrialHTTPError as error:
                        if error.status_code != 404 or result["status"] not in {"failed", "cancelled", "skipped"}:
                            raise
                        row["log_error"] = "Session logs are unavailable for this stopped run (HTTP 404)."
                    row["status"] = "done"
                    row["result_file"] = f"{launch_id}.result.json"
                    row["invalid_reason"] = result.get("invalid_reason")
                    active -= 1
                    print(f"{body.get('variant', launch_id)}: {result['status']}")  # noqa: T201 -- eval script, stdout is the intended output channel
                self.save()
            if all(isinstance(row, dict) and row.get("status") == "done" for row in runs):
                self.manifest["finished_at"] = datetime.now(UTC).isoformat()
                self.save()
                return
            time.sleep(5)
        raise RuntimeError("Polling timed out. Runs retain their saved IDs; resume this manifest to continue polling.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run private live scout variants and save their results.")
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--config-id")
    parser.add_argument(
        "--variants",
        type=Path,
        help="JSON list with label and optional model, reasoning_effort, skill_body, or skill_file.",
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--effort", help="Common effort, required when the source has no effort pin.")
    parser.add_argument("--note", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    if args.concurrency < 1 or args.repeats < 1 or args.timeout < 1:
        parser.error("Concurrency, repeats, and timeout must be positive.")
    token = os.environ.get("POSTHOG_API_KEY")
    if not token:
        parser.error("Set POSTHOG_API_KEY to an operator key with scout and skill write scopes.")
    output = private_output_directory(args.output)
    manifest_path = output / "manifest.json"
    if args.resume:
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("host") != args.host.rstrip("/"):
            parser.error("The host must match the saved manifest.")
    else:
        if manifest_path.exists():
            parser.error("A manifest already exists. Use --resume or a new output directory.")
        if not args.project_id or not args.config_id or not args.variants:
            parser.error("A new comparison requires project-id, config-id, and variants.")
        variants = json.loads(args.variants.read_text())
        if not isinstance(variants, list) or not variants:
            parser.error("Variants must be a nonempty JSON list. Include the current scout as a baseline.")
        runs: list[Json] = []
        for variant in variants:
            if not isinstance(variant, dict) or not isinstance(variant.get("label"), str):
                parser.error("Each variant needs a label.")
            if set(variant) - {"label", "model", "reasoning_effort", "skill_body", "skill_file"}:
                parser.error("A variant contains unsupported fields.")
            if "skill_body" in variant and "skill_file" in variant:
                parser.error("Use skill_body or skill_file, not both.")
            overrides = {key: value for key, value in variant.items() if key not in {"label", "skill_file"}}
            if "skill_file" in variant:
                overrides["skill_body"] = (args.variants.parent / variant["skill_file"]).read_text()
            if args.effort:
                overrides.setdefault("reasoning_effort", args.effort)
            for repeat in range(args.repeats):
                runs.append(
                    {
                        "status": "pending",
                        "request": {
                            "launch_id": str(uuid4()),
                            "variant": f"{variant['label']}:{repeat + 1}",
                            "note": args.note,
                            **overrides,
                        },
                    }
                )
        manifest = {
            "version": 1,
            "host": args.host.rstrip("/"),
            "project_id": args.project_id,
            "config_id": args.config_id,
            "created_at": datetime.now(UTC).isoformat(),
            "runs": runs,
        }
        save_json(manifest_path, manifest)
    comparison = Comparison(TrialClient(args.host, token), output, manifest)
    try:
        comparison.run(args.concurrency, args.timeout)
    except (RuntimeError, ValueError, KeyboardInterrupt) as error:
        comparison.manifest["last_error"] = str(error)
        comparison.save()
        print(f"Stopped: {error}. Saved manifest: {manifest_path}", file=sys.stderr)  # noqa: T201 -- eval script, stdout is the intended output channel
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
