import sys
import json
import hashlib
from decimal import Decimal
from pathlib import Path
from typing import TypedDict


class StageCost(TypedDict):
    model: str
    calls: int
    priced_generations: int
    request_errors: int
    usd: Decimal
    effort: str


def stage_family(stage: str | None) -> str:
    stage = stage or "?"
    if stage.startswith("issues-review"):
        return "review"
    if stage.startswith("blind-spots"):
        return "blind-spot"
    if stage.startswith("validation"):
        return "validation"
    return stage


def add_stage_cost(
    costs: dict[str, StageCost], family: str, model: str, effort: str, calls: int, usd: Decimal | None
) -> None:
    if family not in costs:
        costs[family] = {
            "model": model,
            "calls": 0,
            "priced_generations": 0,
            "request_errors": 0,
            "usd": Decimal(0),
            "effort": effort,
        }
    entry = costs[family]
    entry["calls"] += calls
    if usd is None:
        entry["request_errors"] += calls
    else:
        entry["priced_generations"] += calls
        entry["usd"] += usd
    entry["model"] = ",".join(sorted(set(entry["model"].split(",")) | set(model.split(","))))
    entry["effort"] = ",".join(sorted(set(entry["effort"].split(",")) | set(effort.split(","))))


def audited_request_errors(path: Path, content: bytes, rows: list[dict]) -> set[int]:
    ledger_path = path.with_name(path.name.removesuffix(".ai_usage.json") + ".request_errors.json")
    if not ledger_path.exists():
        return set()
    ledger = json.loads(ledger_path.read_text())
    if (
        not isinstance(ledger, dict)
        or ledger.get("schema_version") != 1
        or ledger.get("usage_file") != path.name
        or ledger.get("usage_sha256") != hashlib.sha256(content).hexdigest()
        or ledger.get("accounting_basis") != "priced_successful_generations"
        or ledger.get("litellm_version") != "1.92.0"
        or not isinstance(ledger.get("source_evidence"), dict)
        or not ledger["source_evidence"]
        or ledger.get("capture_snapshot_complete") is not True
        or ledger.get("raw_rows_matched") != len(rows)
        or ledger.get("successful_generations_missing_cost") != 0
        or ledger.get("priced_error_events") != 0
    ):
        raise ValueError(f"{ledger_path}: invalid or stale request-error audit.")
    errors = ledger.get("errors")
    if not isinstance(errors, list) or not errors:
        raise ValueError(f"{ledger_path}: expected audited request errors.")
    indices: set[int] = set()
    for error in errors:
        if not isinstance(error, dict):
            raise ValueError(f"{ledger_path}: invalid error record.")
        index = error.get("row_index")
        if type(index) is not int or index < 0 or index >= len(rows) or index in indices:
            raise ValueError(f"{ledger_path}: invalid or repeated usage-row index.")
        row = rows[index]
        identity = {key: row.get(key) for key in ("ts", "stage", "model", "session", "effort")}
        if (
            not isinstance(row, dict)
            or "cost" not in row
            or row["cost"] is not None
            or error.get("identity") != identity
            or error.get("is_error") is not True
            or error.get("error") != "litellm.NotFoundError: NotFoundError: OpenAIException - "
            or error.get("http_status") != 404
            or error.get("phase") != "before_response_stream"
            or error.get("usage_fields_present") != []
            or error.get("cost_fields_present") != []
            or "cost_usd" not in error
            or error["cost_usd"] is not None
            or any(row.get(key) != 0 for key in ("in", "out", "reasoning", "cache_read", "cache_write"))
        ):
            raise ValueError(f"{ledger_path}: usage row {index} is not a proven unpriced HTTP 404 request error.")
        indices.add(index)
    if indices != {index for index, row in enumerate(rows) if row.get("cost") is None}:
        raise ValueError(f"{ledger_path}: audited errors must cover every missing dollar value exactly once.")
    if (
        ledger.get("requests") != len(rows)
        or ledger.get("request_errors") != len(indices)
        or ledger.get("priced_generations") != len(rows) - len(indices)
    ):
        raise ValueError(f"{ledger_path}: request and generation counts do not match usage.")
    return indices


def raw_stage_costs(path: Path, families: set[str] | None = None) -> dict[str, StageCost]:
    content = path.read_bytes()
    rows = json.loads(content, parse_float=Decimal)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: expected a list of usage events.")
    request_errors = audited_request_errors(path, content, rows)
    costs: dict[str, StageCost] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("stage"), str | type(None)):
            raise ValueError(f"{path}: invalid usage event at index {index}.")
        family = stage_family(row.get("stage"))
        if family == "capture-probe" or families is not None and family not in families:
            continue
        if index in request_errors:
            add_stage_cost(costs, family, str(row.get("model")), str(row.get("effort")), 1, None)
            continue
        value = row.get("cost")
        if isinstance(value, bool) or not isinstance(value, int | Decimal):
            raise ValueError(f"{path}: event {index} ({family}) has missing or invalid gateway dollars.")
        usd = Decimal(value)
        if not usd.is_finite() or usd < 0:
            raise ValueError(f"{path}: event {index} ({family}) has invalid gateway dollars.")
        add_stage_cost(costs, family, str(row.get("model")), str(row.get("effort")), 1, usd)
    if not costs:
        raise ValueError(f"{path}: no review usage costs found.")
    if not any(stage["priced_generations"] for stage in costs.values()):
        raise ValueError(f"{path}: no priced successful generations found.")
    if families is not None and families - costs.keys():
        raise ValueError(f"{path}: missing composite stages {sorted(families - costs.keys())}.")
    return costs


def markdown_stage_costs(path: Path) -> dict[str, StageCost]:
    costs: dict[str, StageCost] = {}
    in_table = False
    for line in path.read_text().splitlines():
        if not line.startswith("|"):
            if in_table:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[:2] == ["stage family", "model"]:
            in_table = True
            continue
        if not in_table or set(cells[0]) <= {"-", ":", " "} or cells[0] == "capture-probe":
            continue
        if len(cells) != 9 or not cells[7].startswith("$"):
            raise ValueError(f"{path}: stage {cells[0]} has missing gateway dollars.")
        usd = Decimal(cells[7][1:])
        if not usd.is_finite() or usd < 0:
            raise ValueError(f"{path}: stage {cells[0]} has invalid gateway dollars.")
        add_stage_cost(costs, cells[0], cells[1], cells[8], int(cells[2].replace(",", "")), usd)
    if not costs:
        raise ValueError(f"{path}: no stage-family cost rows found.")
    return costs


def load_stage_costs(runs: Path, run: str) -> dict[str, StageCost]:
    raw = runs / f"{run}.ai_usage.json"
    if raw.exists():
        return raw_stage_costs(raw)
    # runs/glm-high-1bc.usage.md records which attempts produced the composite's validated output.
    if run == "glm-high-1bc":
        sources = {
            "glm-high-1b": {"perspective_selection", "review", "blind-spot"},
            "glm-high-1c": {"dedup", "validation"},
        }
        if all((runs / f"{source}.ai_usage.json").exists() for source in sources):
            costs: dict[str, StageCost] = {}
            for source, families in sources.items():
                costs.update(raw_stage_costs(runs / f"{source}.ai_usage.json", families))
            return costs
    markdown = runs / f"{run}.usage.md"
    print(f"{run}: raw usage unavailable; using rounded stage costs from {markdown}.", file=sys.stderr)
    return markdown_stage_costs(markdown)
