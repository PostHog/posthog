from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np

from ..corpus import Corpus
from ..io import JsonObject, parse_epoch, read_jsonl, write_json, write_jsonl
from ..signatures import signature_row
from ..stage import StageContext


class MaterializeCorpora:
    name = "materialize_corpora"

    def input_paths(self, context: StageContext) -> list[Path]:
        split = context.stage_dir("split_territories")
        return [split / "assignments.jsonl", *(split / name for name in self._names(context))]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / name for name in self._names(context)] + [directory / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        return {"territories": list(self._names(context)), "embedding_dtype": "float32"}

    def run(self, context: StageContext) -> None:
        summary: dict[str, JsonObject] = {}
        source = context.stage_dir("split_territories")
        output = context.stage_dir(self.name)
        assignments = [row for _line, row in read_jsonl(source / "assignments.jsonl")]
        linkage_group_of_report = {str(row["report_id"]): str(row["linkage_group_id"]) for row in assignments}
        for name in self._names(context):
            corpus = Corpus.load(source / name / "signals.jsonl", source / name / "reports.jsonl")
            signals = corpus.sorted_signals()
            engine_rows: list[JsonObject] = []
            signatures: list[JsonObject] = []
            embedding_rows: list[list[float]] = []
            for signal in signals:
                document_id = str(signal["document_id"])
                embedding = cast(list[object], signal["embedding"])
                embedding_rows.append([float(value) for value in embedding])
                engine_rows.append(
                    {
                        "id": document_id,
                        "ts": parse_epoch(signal.get("timestamp"), f"signal {document_id}.timestamp"),
                        "content": str(signal.get("content") or ""),
                        "product": str(signal.get("source_product") or ""),
                        "type": str(signal.get("source_type") or ""),
                        "source_id": signal.get("source_id"),
                    }
                )
                signature_value = signal.get("concern_signature")
                signature_embedding = signal.get("concern_signature_embedding")
                if isinstance(signature_value, dict) and isinstance(signature_embedding, list):
                    signatures.append(
                        signature_row(
                            document_id,
                            cast(JsonObject, signature_value),
                            cast(list[object], signature_embedding),
                        )
                    )
            territory = output / name
            write_jsonl(territory / "signals.jsonl", engine_rows)
            np.save(territory / "embeddings.npy", np.asarray(embedding_rows, dtype=np.float32), allow_pickle=False)
            write_jsonl(territory / "sigs.jsonl", signatures)
            write_jsonl(territory / "source_reports.jsonl", corpus.sorted_reports())
            document_groups = {
                document_id: linkage_group_of_report[corpus.report_of[document_id]]
                for document_id in sorted(corpus.report_of)
            }
            write_json(territory / "document_groups.json", document_groups)
            summary[name] = {
                "signals": len(signals),
                "reports": len(corpus.reports),
                "signatures": len(signatures),
                "embedding_shape": [len(embedding_rows), 1536],
                "stream_order": "timestamp then document_id",
            }
        write_json(output / "summary.json", summary)

    @staticmethod
    def _names(context: StageContext) -> tuple[str, str, str]:
        value = context.config.territories["names"]
        names = cast(list[str], value)
        return names[0], names[1], names[2]
