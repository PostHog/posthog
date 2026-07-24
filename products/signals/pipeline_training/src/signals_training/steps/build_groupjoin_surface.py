from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pandas as pd

from ..corpus import Corpus
from ..io import JsonObject, read_jsonl, write_json
from ..lineage import builder_script, python, run_logged
from ..stage import StageContext


@dataclass(frozen=True)
class Evidence:
    label: bool
    weight: float
    source: str
    member: str


def pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def tuple_id(query: str, members: list[str]) -> str:
    return hashlib.sha256((query + "|" + ",".join(sorted(members))).encode()).hexdigest()[:20]


class BuildGroupJoinSurface:
    name = "build_groupjoin_surface"

    def input_paths(self, context: StageContext) -> list[Path]:
        labels = context.stage_dir("prepare_labels") / "train"
        return [
            context.stage_dir("materialize_corpora") / "train",
            context.stage_dir("split_territories") / "train" / "signals.jsonl",
            context.stage_dir("split_territories") / "train" / "reports.jsonl",
            context.stage_dir("harvest_groupjoin") / "harvest",
            labels / "pairs.jsonl",
            labels / "reports.jsonl",
            labels / "operations.jsonl",
            builder_script("groupjoin_features.py"),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "groupjoin_frame.parquet",
            directory / "groupjoin_features.parquet",
            directory / "groupjoin_neural.npz",
            directory / "groupjoin_frame_summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {
            "label_rule": "negative evidence wins; unknown remains unlabeled",
            "state_contract": "exact Rust decision-time candidate views",
            "neural_features": True,
        }

    def run(self, context: StageContext) -> None:
        directory = context.stage_dir(self.name)
        source = context.stage_dir("split_territories") / "train"
        corpus = Corpus.load(source / "signals.jsonl", source / "reports.jsonl")
        exact, report_pairs, coherent = self._load_evidence(context)
        rows: list[dict[str, object]] = []
        harvest = context.stage_dir("harvest_groupjoin") / "harvest"
        for decision_path in sorted(harvest.glob("*/decisions.jsonl")):
            rows.extend(
                self._replay_rows(
                    decision_path,
                    decision_path.parent.name,
                    corpus,
                    exact,
                    report_pairs,
                    coherent,
                )
            )
        if not rows:
            raise ValueError("no groupjoin decisions were harvested")
        frame = pd.DataFrame(rows)
        repeats = frame.groupby("tuple_id")["tuple_id"].transform("size")
        frame["tuple_repeat_count"] = repeats
        frame["sample_weight"] = frame["label_weight"] / repeats
        frame.to_parquet(directory / "groupjoin_frame.parquet", index=False)
        labeled = frame.loc[frame["label_known"]]
        write_json(
            directory / "groupjoin_frame_summary.json",
            {
                "rows": len(frame),
                "unique_tuples": int(frame["tuple_id"].nunique()),
                "labeled_rows": len(labeled),
                "positive_rows": int(labeled["label"].eq(True).sum()),
                "negative_rows": int(labeled["label"].eq(False).sum()),
                "mixed_evidence_rows": int(labeled["mixed_evidence"].sum()),
                "decisions": int(frame["decision_id"].nunique()),
                "by_regime": {str(key): int(value) for key, value in frame.groupby("regime").size().items()},
            },
        )
        run_logged(
            context,
            self.name,
            [
                python(context),
                str(builder_script("groupjoin_features.py")),
                "--build",
                str(directory),
                "--corpus",
                str(context.stage_dir("materialize_corpora") / "train"),
                "--neural",
            ],
        )

    def _load_evidence(
        self, context: StageContext
    ) -> tuple[
        dict[tuple[str, str], Evidence],
        dict[tuple[str, str], tuple[bool, float]],
        dict[str, tuple[bool, float]],
    ]:
        labels = context.stage_dir("prepare_labels") / "train"
        exact: dict[tuple[str, str], Evidence] = {}
        for _line, row in read_jsonl(labels / "pairs.jsonl"):
            if bool(row.get("has_conflict")):
                continue
            left, right = str(row["signal_a"]), str(row["signal_b"])
            exact[pair_key(left, right)] = Evidence(
                bool(row["same_concern"]),
                float(cast(float, row["confidence"])),
                f"exact:{row['provenance']}",
                "",
            )
        report_pairs: dict[tuple[str, str], tuple[bool, float]] = {}
        for _line, row in read_jsonl(labels / "operations.jsonl"):
            if bool(row.get("has_conflict")) or row.get("verdict") not in {"keep_separate", "whole_merge"}:
                continue
            key = pair_key(str(row["left_report_id"]), str(row["right_report_id"]))
            value = (row["verdict"] == "whole_merge", float(cast(float, row["confidence"])))
            if key not in report_pairs or value[1] > report_pairs[key][1]:
                report_pairs[key] = value
        coherent: dict[str, tuple[bool, float]] = {}
        for _line, row in read_jsonl(labels / "reports.jsonl"):
            if bool(row.get("has_conflict")):
                continue
            value: bool | None = None
            if row.get("coherent") is not None:
                value = bool(row["coherent"])
            elif row.get("gold_positive") is True:
                value = True
            elif row.get("known_overgroup") is True:
                value = False
            if value is not None:
                coherent[str(row["report_id"])] = (value, float(cast(float, row["confidence"])))
        return exact, report_pairs, coherent

    def _replay_rows(
        self,
        path: Path,
        regime: str,
        corpus: Corpus,
        exact: dict[tuple[str, str], Evidence],
        report_pairs: dict[tuple[str, str], tuple[bool, float]],
        coherent: dict[str, tuple[bool, float]],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for decision_index, line in enumerate(path.open()):
            decision = json.loads(line)
            query = str(decision["document_id"])
            decision_rows: list[dict[str, object]] = []
            for state in decision.get("candidate_report_states") or []:
                members = [str(member) for member in state["members"]]
                evidence = self._target_evidence(query, members, corpus, exact, report_pairs, coherent)
                positives = [item for item in evidence if item.label]
                negatives = [item for item in evidence if not item.label]
                label: bool | None = False if negatives else True if positives else None
                pointer = max(positives, key=lambda item: item.weight).member if positives else None
                decision_rows.append(
                    {
                        "decision_id": f"{regime}:{decision_index}",
                        "regime": regime,
                        "query": query,
                        "candidate_report": str(state["report_id"]),
                        "members": json.dumps(members, separators=(",", ":")),
                        "tuple_id": tuple_id(query, members),
                        "n_members": int(state["n_members"]),
                        "rank_best": min(int(state["rank_best"]), 25),
                        "n_retrieved": min(int(state["n_retrieved"]), 10),
                        "label": label,
                        "label_known": label is not None,
                        "label_weight": max((item.weight for item in evidence), default=0.0),
                        "positive_evidence": len(positives),
                        "negative_evidence": len(negatives),
                        "mixed_evidence": bool(positives and negatives),
                        "pointer_member": pointer,
                        "group_single_concern": self._group_quality(members, corpus, report_pairs, coherent),
                        "evidence_sources": json.dumps(sorted({item.source for item in evidence})),
                    }
                )
            has_positive = any(row["label"] is True for row in decision_rows)
            for row in decision_rows:
                row["decision_has_positive"] = has_positive
                row["candidate_reports"] = len(decision_rows)
            rows.extend(decision_rows)
        return rows

    @staticmethod
    def _target_evidence(
        query: str,
        members: list[str],
        corpus: Corpus,
        exact: dict[tuple[str, str], Evidence],
        report_pairs: dict[tuple[str, str], tuple[bool, float]],
        coherent: dict[str, tuple[bool, float]],
    ) -> list[Evidence]:
        query_report = corpus.report_of.get(query)
        result: list[Evidence] = []
        for member in members:
            exact_value = exact.get(pair_key(query, member))
            if exact_value is not None:
                result.append(Evidence(exact_value.label, exact_value.weight, exact_value.source, member))
            member_report = corpus.report_of.get(member)
            if query_report is None or member_report is None:
                continue
            if query_report == member_report and query_report in coherent and coherent[query_report][0]:
                result.append(Evidence(True, 0.7 * coherent[query_report][1], "report:coherent", member))
            elif query_report != member_report and pair_key(query_report, member_report) in report_pairs:
                label, weight = report_pairs[pair_key(query_report, member_report)]
                result.append(Evidence(label, weight, "report:operation", member))
        return result

    @staticmethod
    def _group_quality(
        members: list[str],
        corpus: Corpus,
        report_pairs: dict[tuple[str, str], tuple[bool, float]],
        coherent: dict[str, tuple[bool, float]],
    ) -> bool | None:
        reports = sorted({corpus.report_of[member] for member in members if member in corpus.report_of})
        if not reports:
            return None
        known = [coherent[report] for report in reports if report in coherent]
        if any(not label for label, _weight in known):
            return False
        cross = [
            report_pairs[pair_key(left, right)]
            for index, left in enumerate(reports)
            for right in reports[index + 1 :]
            if pair_key(left, right) in report_pairs
        ]
        if any(not label for label, _weight in cross):
            return False
        if len(reports) == 1:
            return known[0][0] if known else None
        expected = len(reports) * (len(reports) - 1) // 2
        if len(known) == len(reports) and len(cross) == expected:
            return all(label for label, _weight in [*known, *cross])
        return None
