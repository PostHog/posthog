from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import cast

from ..io import (
    JsonObject,
    parse_epoch,
    read_jsonl,
    require_nonzero_vector,
    require_string,
    require_string_list,
    write_json,
)
from ..stage import StageContext


class ValidateInputs:
    name = "validate_inputs"

    def input_paths(self, context: StageContext) -> list[Path]:
        inputs = context.config.inputs
        return [
            inputs["signals"],
            inputs["reports"],
            inputs["report_links"],
            inputs["pair_labels"],
            inputs["report_labels"],
            inputs["operation_labels"],
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        return [context.stage_dir(self.name) / "audit.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "embedding_width": 1536,
            "require_exact_report_partition": True,
            "require_concern_signatures": context.config.lineage.get("require_concern_signatures"),
        }

    def run(self, context: StageContext) -> None:
        for name, path in context.config.inputs.items():
            if not path.is_file():
                raise FileNotFoundError(f"inputs.{name}: {path}")

        signals: dict[str, JsonObject] = {}
        source_counts: Counter[str] = Counter()
        timestamps: list[float] = []
        signature_count = 0
        for line_number, row in read_jsonl(context.config.inputs["signals"]):
            location = f"{context.config.inputs['signals']}:{line_number}"
            document_id = require_string(row, "document_id", location)
            if document_id in signals:
                raise ValueError(f"{location}: duplicate document_id {document_id}")
            require_string(row, "content", location)
            source_counts[require_string(row, "source_product", location)] += 1
            require_string(row, "source_type", location)
            timestamps.append(parse_epoch(row.get("timestamp"), f"{location}.timestamp"))
            require_nonzero_vector(row, "embedding", location)
            signature = row.get("concern_signature")
            signature_embedding = row.get("concern_signature_embedding")
            if (signature is None) != (signature_embedding is None):
                raise ValueError(f"{location}: concern_signature and concern_signature_embedding must appear together")
            if signature is not None:
                if not isinstance(signature, dict):
                    raise ValueError(f"{location}: concern_signature must be an object")
                require_nonzero_vector(row, "concern_signature_embedding", location)
                signature_count += 1
            weight = row.get("weight", 0.5)
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(float(weight))
                or float(weight) < 0
            ):
                raise ValueError(f"{location}: weight must be finite and non-negative")
            signals[document_id] = row

        require_signatures = context.config.lineage.get("require_concern_signatures")
        if not isinstance(require_signatures, bool):
            raise ValueError("lineage.require_concern_signatures must be boolean")
        if require_signatures and signature_count != len(signals):
            raise ValueError(
                f"elected lineage requires concern signatures for every signal; "
                f"found {signature_count} of {len(signals)}"
            )

        reports: dict[str, list[str]] = {}
        report_of: dict[str, str] = {}
        for line_number, row in read_jsonl(context.config.inputs["reports"]):
            location = f"{context.config.inputs['reports']}:{line_number}"
            report_id = require_string(row, "report_id", location)
            if report_id in reports:
                raise ValueError(f"{location}: duplicate report_id {report_id}")
            members = require_string_list(row, "member_ids", location, non_empty=True)
            for member in members:
                if member not in signals:
                    raise ValueError(f"{location}: unknown member {member}")
                if member in report_of:
                    raise ValueError(f"{location}: {member} also belongs to report {report_of[member]}")
                report_of[member] = report_id
            reports[report_id] = members
        missing_membership = sorted(set(signals) - set(report_of))
        if missing_membership:
            sample = ", ".join(missing_membership[:5])
            raise ValueError(f"{len(missing_membership)} signals are absent from reports, including {sample}")

        link_count = 0
        for line_number, row in read_jsonl(context.config.inputs["report_links"]):
            location = f"{context.config.inputs['report_links']}:{line_number}"
            left = require_string(row, "report_a", location)
            right = require_string(row, "report_b", location)
            if left == right or left not in reports or right not in reports:
                raise ValueError(f"{location}: link must reference two distinct known reports")
            cosine = row.get("max_cosine")
            if (
                isinstance(cosine, bool)
                or not isinstance(cosine, (int, float))
                or not math.isfinite(float(cosine))
                or not -1 <= float(cosine) <= 1
            ):
                raise ValueError(f"{location}: max_cosine must be finite and in [-1, 1]")
            for name, report_id in (("overlap_a", left), ("overlap_b", right)):
                overlap = row.get(name)
                if (
                    isinstance(overlap, bool)
                    or not isinstance(overlap, int)
                    or not 0 <= overlap <= len(reports[report_id])
                ):
                    raise ValueError(f"{location}: {name} must be an integer bounded by its report size")
            link_count += 1

        pair_labels = 0
        for line_number, row in read_jsonl(context.config.inputs["pair_labels"]):
            location = f"{context.config.inputs['pair_labels']}:{line_number}"
            left = require_string(row, "signal_a", location)
            right = require_string(row, "signal_b", location)
            if left == right or left not in signals or right not in signals:
                raise ValueError(f"{location}: pair must reference two distinct known signals")
            self._validate_judgment(row, location)
            if not isinstance(row.get("same_concern"), bool):
                raise ValueError(f"{location}: same_concern must be boolean")
            pair_labels += 1

        report_labels = 0
        for line_number, row in read_jsonl(context.config.inputs["report_labels"]):
            location = f"{context.config.inputs['report_labels']}:{line_number}"
            report_id = require_string(row, "report_id", location)
            if report_id not in reports:
                raise ValueError(f"{location}: unknown report")
            if not any(
                (
                    row.get("coherent") is not None,
                    row.get("gold_positive") is True,
                    row.get("known_overgroup") is True,
                    row.get("components") is not None,
                    row.get("outcome") is not None,
                )
            ):
                raise ValueError(f"{location}: report label contains no judgment")
            components = row.get("components")
            if components is not None:
                if not isinstance(components, list) or not components:
                    raise ValueError(f"{location}: components must be a non-empty array or null")
                seen: set[str] = set()
                for index, component in enumerate(components):
                    if not isinstance(component, list) or not component:
                        raise ValueError(f"{location}: components[{index}] must be non-empty")
                    values = set(component)
                    if len(values) != len(component) or not all(isinstance(value, str) for value in component):
                        raise ValueError(f"{location}: components[{index}] contains invalid or duplicate IDs")
                    if not values.issubset(reports[report_id]) or seen & values:
                        raise ValueError(f"{location}: components must be disjoint subsets of report members")
                    seen.update(cast(set[str], values))
            self._validate_judgment(row, location)
            report_labels += 1

        operation_labels = 0
        operation_ids: set[str] = set()
        for line_number, row in read_jsonl(context.config.inputs["operation_labels"]):
            location = f"{context.config.inputs['operation_labels']}:{line_number}"
            operation_id = require_string(row, "operation_id", location)
            if operation_id in operation_ids:
                raise ValueError(f"{location}: duplicate operation_id {operation_id}")
            operation_ids.add(operation_id)
            left = require_string(row, "left_report_id", location)
            right = require_string(row, "right_report_id", location)
            if left == right or left not in reports or right not in reports:
                raise ValueError(f"{location}: operation must reference two distinct known reports")
            verdict = row.get("verdict")
            if verdict not in {"keep_separate", "whole_merge", "subset", "ambiguous"}:
                raise ValueError(f"{location}: invalid verdict {verdict!r}")
            if verdict == "subset":
                selected_left = require_string_list(row, "selected_left", location, non_empty=True)
                selected_right = require_string_list(row, "selected_right", location, non_empty=True)
                if not set(selected_left).issubset(reports[left]) or not set(selected_right).issubset(reports[right]):
                    raise ValueError(f"{location}: subset members must belong to their stated report side")
            secondary_verdict = row.get("secondary_verdict")
            if secondary_verdict not in {None, "keep_separate", "whole_merge", "subset", "ambiguous"}:
                raise ValueError(f"{location}: invalid secondary_verdict {secondary_verdict!r}")
            if secondary_verdict is not None:
                require_string(row, "secondary_reader", location)
            if secondary_verdict == "subset":
                secondary_left = require_string_list(row, "secondary_selected_left", location, non_empty=True)
                secondary_right = require_string_list(row, "secondary_selected_right", location, non_empty=True)
                if not set(secondary_left).issubset(reports[left]) or not set(secondary_right).issubset(reports[right]):
                    raise ValueError(f"{location}: secondary subset members must belong to their stated report side")
            self._validate_judgment(row, location)
            operation_labels += 1

        write_json(
            self.output_paths(context)[0],
            {
                "signals": len(signals),
                "reports": len(reports),
                "report_links": link_count,
                "pair_labels": pair_labels,
                "report_labels": report_labels,
                "operation_labels": operation_labels,
                "signature_coverage": signature_count / max(len(signals), 1),
                "source_products": dict(sorted(source_counts.items())),
                "first_timestamp": min(timestamps, default=None),
                "last_timestamp": max(timestamps, default=None),
                "partition_complete": True,
            },
        )

    @staticmethod
    def _validate_judgment(row: JsonObject, location: str) -> None:
        require_string(row, "provenance", location)
        confidence = row.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            raise ValueError(f"{location}: confidence must be in [0, 1]")
