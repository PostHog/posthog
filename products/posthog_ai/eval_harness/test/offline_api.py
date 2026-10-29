from __future__ import annotations

import json
from uuid import UUID, uuid5

import httpx


class OfflineServer:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.items: dict[str, object] = {}
        self.results: dict[tuple[str, str], object] = {}
        self.experiment: dict[str, object] = {}
        self.status = "uploading"
        self.tags: list[str] = []

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if request.method == "PATCH":
            self.tags = body["tags"]
            return httpx.Response(200, json={"id": self.experiment["id"], "tags": self.tags})
        now = str(self.experiment.get("started_at", body.get("started_at")))
        if request.url.path.endswith("/upload/"):
            item_receipts = []
            result_receipts = []
            for item in body["items"]:
                item_receipts.append({"id": item["id"], "created": item["id"] not in self.items, "accepted_at": now})
                assert self.items.setdefault(item["id"], item) == item
            for result in body["results"]:
                identity = (result["item_id"], result["scorer_version_id"])
                result_receipts.append(
                    {
                        "id": str(uuid5(UUID(str(self.experiment["id"])), str(identity))),
                        "item_id": identity[0],
                        "scorer_version_id": identity[1],
                        "created": identity not in self.results,
                        "accepted_at": now,
                    }
                )
                assert self.results.setdefault(identity, result) == result
            return httpx.Response(200, json={"items": item_receipts, "results": result_receipts})
        closing = request.url.path.endswith(("/complete/", "/fail/"))
        if closing:
            self.status = "completed" if request.url.path.endswith("/complete/") else "failed"
        else:
            if self.experiment:
                assert body == self.experiment
            self.experiment = body
        return httpx.Response(
            200,
            json={
                "id": self.experiment["id"],
                "status": self.status,
                "created": not closing,
                "started_at": now,
                "created_at": now,
                "finished_at": now if closing else None,
                "expected_item_count": self.experiment.get("expected_item_count"),
                "expected_result_count": self.experiment.get("expected_result_count"),
                "accepted_item_count": len(self.items),
                "accepted_result_count": len(self.results),
            },
        )
