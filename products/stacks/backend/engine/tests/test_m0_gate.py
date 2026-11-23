import os
import re
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from products.stacks.backend.engine.addresses import LAYOUT, address
from products.stacks.backend.engine.mappings import PROVIDER_VERSION, load_mapping
from products.stacks.backend.engine.tests.test_binding_lifecycle import _project
from products.stacks.backend.engine.translate_in import translate_in
from products.stacks.backend.engine.types import Binding, Identity

ROOT = Path(__file__).resolve().parents[5]
STACK = ROOT / ".ph/us/project-2/slo-monitoring"
ORIGINAL = ROOT / "terraform/us/project-2/team-analytics-platform/slo-monitoring"
STACKS = json.loads((ROOT / "posthog.json").read_bytes())["stacks"]
ORIGINALS = {
    folder.name: folder
    for folder in (ROOT / "terraform/us/project-2").glob("team-*/*")
    if folder.name in STACKS and any(folder.glob("*.tf"))
}
IMPORT = re.compile(r'^import\s*\{\s*to\s*=\s*(\w+\.\w+)\s+id\s*=\s*"((?:\d+/)?\d+)"\s*\}', re.MULTILINE)
TOFU = shutil.which("tofu")
pytestmark = pytest.mark.skipif(TOFU is None, reason="OpenTofu is unavailable")


def _imports(original: Path) -> dict[str, str]:
    imports: dict[str, str] = {}
    for file in original.glob("*.tf"):
        text = file.read_text()
        blocks = IMPORT.findall(text)
        assert len(re.findall(r"^import\s*\{", text, re.MULTILINE)) == len(blocks), file
        for target, entity_id in blocks:
            assert target not in imports, target
            imports[target] = entity_id
    return imports


def _loopback(host: str) -> None:
    url = urlsplit(host)
    assert (url.scheme, url.hostname) == ("http", "127.0.0.1") and url.port


def _assemble_original(directory: Path, original: Path, host: str, *, include_imports: bool = True) -> None:
    _loopback(host)
    for file in original.glob("*.tf"):
        text = file.read_text()
        assert not re.search(r'^\s*(?:provider|module|data|terraform)\s+["{]', text, re.MULTILINE), file
        (directory / file.name).write_text(text if include_imports else IMPORT.sub("", text))
    for ancestor in original.parents[:4]:
        for template in ancestor.glob("*.tf.tpl"):
            contents = template.read_text()
            if template.name == "providers_root.tf.tpl":
                # The legacy folder pins a Terraform CLI release. Both sides use the same OpenTofu binary and provider.
                contents, count = re.subn(r'^\s*required_version\s*=\s*"[^"]+"', "", contents, flags=re.MULTILINE)
                assert count == 1
                contents, count = re.subn(r'(?m)^(\s*version\s*=\s*)"[^"]+"', rf'\g<1>"{PROVIDER_VERSION}"', contents)
                assert count == 1
            elif template.name in {"locals_region.tf.tpl", "providers_region.tf.tpl"}:
                field = "posthog_host" if template.name.startswith("locals_") else "host"
                contents, count = re.subn(rf"(?m)^(\s*{field}\s*=\s*).+$", rf"\g<1>{json.dumps(host)}", contents)
                assert count == 1, template
            (directory / template.stem).write_text(contents)
    team = (original.parent / "terragrunt.hcl").read_text()
    inputs = re.search(r"^inputs\s*=\s*\{(.*?)^\}", team, re.MULTILINE | re.DOTALL)
    assert inputs, "The team inputs block is missing"
    (directory / "team.auto.tfvars").write_text(inputs[1])


def _plan(directory: Path, host: str = "http://127.0.0.1:1") -> dict[str, dict[str, Any]]:
    assert TOFU
    _loopback(host)
    mirror = os.getenv("POSTHOG_STACK_MIRROR")
    assert mirror, "Set POSTHOG_STACK_MIRROR to the installed mirror"
    source = f"filesystem_mirror {{\n path = {json.dumps(str(Path(mirror).resolve()))}\n }}"
    config = directory / "gate.tfrc"
    config.write_text(f"provider_installation {{\n {source}\n}}\n")
    (directory / "host_override.tf.json").write_text(json.dumps({"provider": {"posthog": {"host": host}}}))
    env = {
        "HOME": str(directory),
        "PATH": os.defpath,
        "TF_CLI_CONFIG_FILE": str(config),
        "TF_IN_AUTOMATION": "1",
        "CHECKPOINT_DISABLE": "1",
        "TF_VAR_posthog_api_key": "example-key",
        "POSTHOG_API_KEY": "example-key",
        "POSTHOG_HOST": host,
        "POSTHOG_PROJECT_ID": "2",
        "http_proxy": "http://127.0.0.1:1",
        "https_proxy": "http://127.0.0.1:1",
        "no_proxy": "127.0.0.1",
    }

    def run(*args: str) -> bytes:
        result = subprocess.run([TOFU, *args], cwd=directory, env=env, capture_output=True, check=False, timeout=90)
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout

    run("init", "-get=false", "-input=false", "-no-color")
    run("plan", "-refresh=false", "-input=false", "-no-color", "-out=gate.diff")
    plan = json.loads(run("show", "-json", "gate.diff"))
    return {row["address"]: row["change"] for row in plan["resource_changes"]}


def _values(change: dict[str, Any], kind: str, layout: bool) -> dict[str, Any]:
    mapping = load_mapping(kind)
    attrs = dict(change["after"])
    if layout:
        attrs["tiles"] = [dict(tile) for tile in attrs["tiles"]]
        rows = attrs["tiles"]
        mapping = mapping["layout"]
    else:
        rows = [attrs]
    for row in rows:
        for path in mapping["json_fields"]:
            key = mapping["fields"][path]
            if isinstance(row.get(key), str):
                row[key] = json.loads(row[key])
    return {"values": attrs, "unknown": change["after_unknown"]}


def _assert_values(old: str, expected: dict[str, Any], actual: dict[str, Any], kind: str, layout: bool) -> None:
    left, right = _values(expected, kind, layout), _values(actual, kind, layout)
    for section, attrs in left.items():
        assert attrs.keys() == right[section].keys(), (old, section)
        for field, value in attrs.items():
            # Python equality treats a boolean and its corresponding integer as equal. The JSON types matter here.
            assert json.dumps(value, sort_keys=True) == json.dumps(right[section][field], sort_keys=True), (
                old,
                section,
                field,
            )


def test_original_provider_host_is_pinned_before_any_command(tmp_path: Path) -> None:
    host = "http://127.0.0.1:1"
    _assemble_original(tmp_path, ORIGINAL, host)
    assert host in (tmp_path / "providers_region.tf").read_text()
    assert host in (tmp_path / "locals_region.tf").read_text()


@pytest.mark.skipif(not os.getenv("POSTHOG_STACK_MIRROR"), reason="This fixture uses the installed stack mirror")
def test_composed_description_with_unknown_ids_can_be_planned(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "description.json"
    engine_input = translate_in(
        json.loads(fixture.read_bytes()),
        [],
        {"rename_map": {'posthog_insight.delivery["email"]': {"kind": "insight", "key": "volume"}}},
    )
    (tmp_path / "main.tf.json").write_text(json.dumps(engine_input.config))
    rows = _plan(tmp_path)
    assert len(rows) == 6
    assert rows[address("destination", "notify")]["after_unknown"]["filters_json"] is True
    layout = rows[address("dashboard", "sample", layout=True)]
    assert layout["after"]["tiles"][2]["text_body"] == "Show ${this} and %{that} literally."
    assert [tile.get("insight_id") for tile in layout["after_unknown"]["tiles"][:2]] == [True, True]


def _import_routes(imports: dict[str, str]) -> dict[str, object]:
    routes: dict[str, object] = {}
    for old, value in imports.items():
        entity_id = int(value.rsplit("/", 1)[-1])
        if old.startswith("posthog_insight."):
            routes[f"/api/projects/2/insights/{entity_id}/"] = {
                "id": entity_id,
                "short_id": f"sample{entity_id}",
                "name": "Earlier insight",
                "description": "",
                "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}},
                "tags": [],
                "dashboards": [],
                "deleted": False,
            }
        else:
            assert old.startswith(("posthog_dashboard.", LAYOUT + ".")), old
            routes[f"/api/projects/2/dashboards/{entity_id}/"] = {
                "id": entity_id,
                "name": "Earlier dashboard",
                "pinned": False,
                "tags": [],
                "deleted": False,
                "tiles": [],
            }
    return routes


def _generated_imports(
    renames: dict[str, Identity], imports: dict[str, str]
) -> tuple[list[Binding], list[dict[str, str]]]:
    bindings: list[Binding] = []
    layouts = []
    for old, raw in imports.items():
        target = renames[old]
        entity_id = int(raw.rsplit("/", 1)[-1])
        if old.startswith(LAYOUT + "."):
            # SLOs imports only the layout. A dashboard binding would also import the dashboard and change its ID from unknown to known.
            primary = old.replace(LAYOUT + ".", "posthog_dashboard.", 1)
            if primary not in imports:
                layouts.append({"to": address("dashboard", target["key"], layout=True), "id": raw})
        else:
            bindings.append({**target, "entity_id": entity_id, "status": "pending"})
    return bindings, layouts


def test_gate_covers_every_ported_folder() -> None:
    assert set(STACKS) - set(ORIGINALS) == {"app-events"}
    assert {
        "slo-monitoring",
        "slos",
        "dashboard-key-metrics",
        "community-credit-alerts",
        "partner-billing-alerts",
        "workflow-repair-alerts",
    } <= set(ORIGINALS)
    assert Counter(key.split(".")[0] for key in _imports(ORIGINALS["dashboard-key-metrics"])) == {
        "posthog_insight": 8,
        "posthog_dashboard": 1,
        LAYOUT: 1,
    }
    assert list(_imports(ORIGINALS["slos"])) == [LAYOUT + ".team_analytics_platform_slos"]


@pytest.mark.parametrize(
    ("stack_name", "include_imports"),
    [
        *((name, True) for name in sorted(ORIGINALS)),
        *((name, False) for name in sorted(ORIGINALS) if _imports(ORIGINALS[name])),
    ],
)
def test_original_folder_and_generated_description_plan_the_same_values(
    tmp_path: Path, stack_name: str, include_imports: bool
) -> None:
    folder = ROOT / STACKS[stack_name]["dir"]
    hcl = ORIGINALS[stack_name]
    original, generated = tmp_path / "original", tmp_path / "generated"
    original.mkdir()
    generated.mkdir()
    renames = json.loads((folder / "rename-map.json").read_bytes())
    imports = _imports(hcl) if include_imports else {}
    bindings, layout_only = _generated_imports(renames, imports)
    config = translate_in(
        json.loads((folder / "description.json").read_bytes()), bindings, {"rename_map": renames}
    ).config
    if layout_only:
        config.setdefault("import", []).extend(layout_only)
    routes = _import_routes(imports)
    with _project(routes) as (credentials, requests):
        host = credentials["host"]
        _assemble_original(original, hcl, host, include_imports=include_imports)
        (generated / "main.tf.json").write_text(json.dumps(config))
        before = _plan(original, host)
        assert set(requests) == {("GET", route) for route in routes}
        requests.clear()
        after = _plan(generated, host)
        assert set(requests) == {("GET", route) for route in routes}
    assert before.keys() == renames.keys(), stack_name
    targets = set()
    for old, target in sorted(renames.items()):
        kind = target["kind"]
        layout = old.split(".")[0] == LAYOUT
        new = address(kind, target["key"], layout=layout)
        assert new not in targets and new in after, (old, new)
        targets.add(new)
        assert before[old]["actions"] == after[new]["actions"], old
        if old in imports:
            expected_id = imports[old].rsplit("/", 1)[-1]
            for row in [before[old], after[new]]:
                assert row["importing"]["id"].rsplit("/", 1)[-1] == expected_id
                assert str(row["before"]["id"]) == expected_id
        else:
            assert before[old]["actions"] == ["create"] and "importing" not in after[new]
        _assert_values(old, before[old], after[new], kind, layout)
    assert targets == after.keys(), "The generated description must have exactly one target for each old definition"


@pytest.mark.skipif(
    not os.getenv("POSTHOG_STACK_PREVIOUS_MIRROR"), reason="This comparison needs the previous release mirror"
)
def test_generated_slo_values_across_the_provider_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    description, rename_map = STACK / "description.json", STACK / "rename-map.json"
    if not description.is_file() or not rename_map.is_file():
        pytest.skip("The ported SLO monitoring stack is required for the upgrade comparison")
    renames = json.loads(rename_map.read_bytes())
    config = translate_in(json.loads(description.read_bytes()), [], {"rename_map": renames}).config
    current, previous = tmp_path / "current", tmp_path / "previous"
    current.mkdir()
    previous.mkdir()
    (current / "main.tf.json").write_text(json.dumps(config))
    latest = _plan(current)
    config["terraform"]["required_providers"]["posthog"]["version"] = "1.0.24"
    (previous / "main.tf.json").write_text(json.dumps(config))
    monkeypatch.setenv("POSTHOG_STACK_MIRROR", os.environ["POSTHOG_STACK_PREVIOUS_MIRROR"])
    prior = _plan(previous)
    assert latest.keys() == prior.keys()
    for old, target in renames.items():
        kind = target["kind"]
        layout = old.startswith(LAYOUT + ".")
        name = address(kind, target["key"], layout=layout)
        assert prior[name]["after_sensitive"] == latest[name]["after_sensitive"], (name, "sensitivity")
        _assert_values(name, prior[name], latest[name], kind, layout)
