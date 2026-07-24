from __future__ import annotations

from pathlib import Path

from ..io import JsonObject, read_jsonl, require_string, require_string_list, write_json, write_jsonl
from ..stage import StageContext


class ImportExport:
    name = "import_export"

    def input_paths(self, context: StageContext) -> list[Path]:
        directory = context.config.source_path("export_directory")
        return [directory / "signals.jsonl", directory / "reports.jsonl"]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "signals.jsonl", directory / "reports.jsonl", directory / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {"contract": "export-directory-v1", "files": ["signals.jsonl", "reports.jsonl"]}

    def run(self, context: StageContext) -> None:
        signals_path, reports_path = self.input_paths(context)
        if not signals_path.is_file() or not reports_path.is_file():
            raise FileNotFoundError(
                f"source.export_directory must contain signals.jsonl and reports.jsonl: {signals_path.parent}"
            )

        signals: dict[str, JsonObject] = {}
        for line_number, row in read_jsonl(signals_path):
            location = f"{signals_path}:{line_number}"
            document_id = require_string(row, "document_id", location)
            if document_id in signals:
                raise ValueError(f"{location}: duplicate document_id {document_id}")
            require_string(row, "content", location)
            require_string(row, "source_product", location)
            require_string(row, "source_type", location)
            signals[document_id] = row

        reports: dict[str, JsonObject] = {}
        observed_members: set[str] = set()
        for line_number, row in read_jsonl(reports_path):
            location = f"{reports_path}:{line_number}"
            report_id = require_string(row, "report_id", location)
            if report_id in reports:
                raise ValueError(f"{location}: duplicate report_id {report_id}")
            members = require_string_list(row, "member_ids", location, non_empty=True)
            unknown = sorted(set(members) - set(signals))
            if unknown:
                raise ValueError(f"{location}: unknown member {unknown[0]}")
            duplicate = observed_members.intersection(members)
            if duplicate:
                raise ValueError(f"{location}: member {sorted(duplicate)[0]} appears in more than one report")
            observed_members.update(members)
            reports[report_id] = row

        unassigned = sorted(set(signals) - observed_members)
        if unassigned:
            raise ValueError(f"{len(unassigned)} exported signals have no report, including {unassigned[0]}")

        directory = context.stage_dir(self.name)
        write_jsonl(directory / "signals.jsonl", (signals[key] for key in sorted(signals)))
        write_jsonl(directory / "reports.jsonl", (reports[key] for key in sorted(reports)))
        write_json(
            directory / "summary.json",
            {
                "signals": len(signals),
                "reports": len(reports),
                "exact_partition": True,
                "source_contract": "signals.jsonl plus reports.jsonl",
            },
        )
