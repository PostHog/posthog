import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from posthog.clickhouse.client.execute import sync_execute
from posthog.test.base import BaseTest
from products.editor.backend.models.codebase import Codebase


class CatalogEntry(BaseModel):
    team_id: int | None = Field(default=None)
    user_id: int | None = Field(default=None)
    codebase_id: str | None = Field(default=None)
    artifact_id: str
    parent_artifact_id: str | None = Field(default=None)
    branch: str | None = Field(default=None)
    type: str = Field(default="dir")
    sign: int = Field(default=1)
    timestamp: datetime | None = Field(default=None)


class EditorTestQueryHelpersMixin(BaseTest):
    codebase: Codebase
    stable_user_id: int = 99999

    def _create_artifacts(self, tree: list[dict[str, Any]], user_id: int | None = None, codebase_id: str | None = None):
        query = "INSERT INTO codebase_embeddings (team_id, user_id, codebase_id, artifact_id, chunk_id, vector, properties, timestamp, is_deleted) VALUES "
        rows: list[str] = []

        args = {
            "team_id": self.team.id,
            "user_id": user_id or self.user.id,
            "codebase_id": codebase_id or self.codebase.id,
            "vector": [0.5, 0.5],
            "properties": json.dumps(
                {
                    "lineStart": 0,
                    "lineEnd": 30,
                    "path": "obfuscated_path",
                }
            ),
            "is_deleted": 0,
        }

        for idx, node in enumerate(tree):
            if node["type"] == "file":
                args.update(
                    {
                        f"artifact_id_{idx}": node["id"],
                        f"chunk_id_{idx}": node.get("chunk_id", 0),
                        f"is_deleted_{idx}": node.get("is_deleted", 0),
                        f"timestamp_{idx}": node.get("timestamp"),
                    }
                )
                rows.append(
                    f"(%(team_id)s, %(user_id)s, %(codebase_id)s, %(artifact_id_{idx})s, %(chunk_id_{idx})s, %(vector)s, %(properties)s, %(timestamp_{idx})s, %(is_deleted_{idx})s)"
                )

        sync_execute(query + ", ".join(rows), args, team_id=self.team.id)

    def _create_codebase_catalog(self, tree: list[CatalogEntry]):
        query = "INSERT INTO codebase_catalog (team_id, user_id, codebase_id, artifact_id, parent_artifact_id, branch, type, timestamp, sign) VALUES "
        rows: list[str] = []
        args = {}

        for idx, node in enumerate(tree):
            args.update(
                {
                    f"team_id_{idx}": node.team_id or self.team.id,
                    f"user_id_{idx}": node.user_id or self.stable_user_id,
                    f"codebase_id_{idx}": node.codebase_id or str(self.codebase.id),
                    f"artifact_id_{idx}": node.artifact_id,
                    f"parent_artifact_id_{idx}": node.parent_artifact_id,
                    f"branch_{idx}": node.branch or "",
                    f"type_{idx}": node.type,
                    f"timestamp_{idx}": node.timestamp,
                    f"sign_{idx}": node.sign,
                }
            )
            rows.append(
                f"(%(team_id_{idx})s, %(user_id_{idx})s, %(codebase_id_{idx})s, %(artifact_id_{idx})s, %(parent_artifact_id_{idx})s, %(branch_{idx})s, %(type_{idx})s, %(timestamp_{idx})s, %(sign_{idx})s)"
            )

        sync_execute(query + ", ".join(rows), args, team_id=self.team.id)
