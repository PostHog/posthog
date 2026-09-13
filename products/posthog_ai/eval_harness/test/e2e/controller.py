from __future__ import annotations

import json
import logging
import secrets
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import requests
from pydantic import JsonValue

from .attempt import Attempt
from .faults import FaultName
from .replay import ResponseStep, encoded_text, fixture_events, object_value, sse_frames


class Controller:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.token = secrets.token_urlsafe(32)
        self.attempt: Attempt | None = None
        self.errors: list[str] = []
        self.proxy_targets: dict[str, str] = {}
        self.lock = threading.Lock()
        self.log_lock = threading.Lock()
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                self.handle_request()

            def do_POST(self) -> None:
                self.handle_request()

            def do_PATCH(self) -> None:
                self.handle_request()

            def handle_request(self) -> None:
                from django.db import connections

                try:
                    body = object_value(
                        json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                    )
                    status, content_type, response = controller.handle(
                        self.command,
                        urlparse(self.path).path,
                        dict(self.headers),
                        body,
                    )
                except Exception as error:
                    if not self.path.startswith("/control/"):
                        controller.record_error(f"{type(error).__name__}: {error}")
                    logging.getLogger(__name__).exception("AI E2E request failed: %s %s", self.command, self.path)
                    status = 500 if self.path.startswith("/control/") else 400
                    content_type, response = "application/json", json.dumps({"error": str(error)}).encode()
                finally:
                    connections.close_all()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                if isinstance(response, bytes):
                    self.send_header("Content-Length", str(len(response)))
                else:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                try:
                    for chunk in [response] if isinstance(response, bytes) else response:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as error:
                    controller.record_error(f"{type(error).__name__}: {error}")
                    raise

        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def record_error(self, message: str) -> None:
        (self.attempt.errors if self.attempt else self.errors).append(message)

    def require_attempt(self, attempt_id: str) -> Attempt:
        if self.attempt is None or self.attempt.id != attempt_id:
            raise ValueError("Unknown or stale attempt")
        return self.attempt

    def json(self, data: JsonValue, status: int = 200) -> tuple[int, str, bytes]:
        return status, "application/json", json.dumps(data).encode()

    def handle(
        self, method: str, path: str, headers: dict[str, str], body: dict[str, JsonValue]
    ) -> tuple[int, str, bytes | Iterator[bytes]]:
        headers = {key.lower(): value for key, value in headers.items()}
        if path.startswith("/control/"):
            if not secrets.compare_digest(headers.get("authorization", ""), f"Bearer {self.token}"):
                return self.json({"error": "Invalid controller token"}, 403)
            return self.json(self.control(method, path.removeprefix("/control/"), body))
        attempt = self.attempt
        if attempt is None:
            raise ValueError(f"Request outside an attempt: {method} {path}")
        with self.log_lock, (attempt.output / "requests.ndjson").open("a") as log:
            log.write(json.dumps({"method": method, "path": path}) + "\n")
        if method == "GET" and path == "/billing/api/billing":
            return self.json({"customer": None})
        if method == "GET" and path == "/billing/api/products-v2":
            return self.json({"products": []})
        if method == "GET" and path == "/billing/api/v2/usage/team_options/":
            return self.json({"team_id_options": []})
        if method == "GET" and path in {"/billing/api/v2/usage/", "/billing/api/v2/spend/"}:
            return self.json({"status": "ok", "type": "timeseries", "customer_id": "synthetic", "results": []})
        if method == "PATCH" and path == "/billing/api/billing/":
            if body.get("org_customer_email") not in attempt.emails:
                raise ValueError("Billing update belongs to another attempt")
            return self.json({})
        if path == f"/proxy/{attempt.id}/command" and method == "POST":
            import jwt

            from products.tasks.backend.logic.services.connection_token import get_sandbox_jwt_public_key

            claims = jwt.decode(
                headers.get("authorization", "").removeprefix("Bearer "),
                get_sandbox_jwt_public_key(),
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
            if claims.get("run_id") != attempt.run_id or str(claims.get("team_id")) != str(attempt.team.id):
                raise ValueError("Proxy command belongs to another attempt")
            if body.get("method") != "permission_response":
                raise ValueError("Proxy only accepts permission responses")
            request_id = str(object_value(body.get("params"))["requestId"])
            if attempt.faults["approval"].reach(request_id):
                return self.json({"error": "No active session for this run"}, 400)
            target = self.proxy_targets[attempt.id]
            response = requests.post(
                f"{target}/command", json=body, headers={"Authorization": headers["authorization"]}, timeout=30
            )
            attempt.faults["approval"].record("forwarded", request_id=request_id, status=response.status_code)
            confirmation = attempt.faults["approval_confirmation"]
            if response.ok and (generation := confirmation.reach(request_id)):
                confirmation.wait_for_release(generation)
            return response.status_code, "application/json", response.content
        if method == "GET" and path in {"/v1/models", "/posthog_ai/v1/models", "/posthog_code/v1/models"}:
            project = headers.get("x-posthog-project-id")
            if project is not None and project != str(attempt.team.id):
                raise ValueError("Model discovery belongs to another project")
            return self.json(
                {
                    "object": "list",
                    "has_more": False,
                    "data": [
                        {
                            "id": "claude-sonnet-4-6",
                            "object": "model",
                            "type": "model",
                            "display_name": "Claude Sonnet 4.6",
                            "created_at": "2026-01-01T00:00:00Z",
                            "created": 0,
                            "owned_by": "anthropic",
                            "context_window": 200000,
                        },
                        {
                            "id": "gpt-5.5",
                            "object": "model",
                            "type": "model",
                            "display_name": "GPT 5.5",
                            "created_at": "2026-01-01T00:00:00Z",
                            "created": 0,
                            "owned_by": "openai",
                            "context_window": 272000,
                        },
                    ],
                }
            )
        if method == "GET" and path == "/v1/usage/posthog_code":
            return self.json({"is_rate_limited": False, "is_pro": True})
        if method != "POST":
            raise ValueError(f"Unexpected model request: {method} {path}")
        if path == "/title/v1/messages":
            if (
                body.get("model") != "claude-haiku-4-5-20251001"
                or body.get("stream") is not True
                or attempt.id not in json.dumps(body)
            ):
                raise ValueError("Unexpected Django title request")
            attempt.title_requests += 1
            step = ResponseStep(
                provider="claude",
                model="claude-haiku-4-5-20251001",
                fixture="text",
                user_message="",
                substitutions={
                    "message_id": f"msg_title_{attempt.id}",
                    "model": "claude-haiku-4-5-20251001",
                    "text": "Synthetic conversation",
                },
            )
            return 200, "text/event-stream", sse_frames(fixture_events(step))
        properties = object_value(json.loads(headers.get("x-posthog-properties", "{}")))
        run_id = properties.get("task_run_id", headers.get("x-posthog-property-task_run_id"))
        team_id = properties.get(
            "team_id", headers.get("x-posthog-project-id", headers.get("x-posthog-property-team_id"))
        )
        if str(run_id) != attempt.run_id or str(team_id) != str(attempt.team.id):
            raise ValueError(f"Uncorrelated model request for project {team_id}, run {run_id}")
        with self.log_lock, (attempt.output / "model-requests.ndjson").open("a") as log:
            log.write(json.dumps({"path": path, "body": body}) + "\n")
        if path in {"/v1/messages/count_tokens", "/posthog_ai/v1/messages/count_tokens"}:
            if attempt.provider != "claude" or body.get("model") != attempt.model:
                raise ValueError("Unexpected token-count model")
            return self.json({"input_tokens": 100})
        system = body.get("system")
        if isinstance(system, list) and any(
            isinstance(block, dict) and str(block.get("text", "")).startswith("You are naming a coding session ")
            for block in system
        ):
            if (
                path not in {"/v1/messages", "/posthog_ai/v1/messages"}
                or attempt.provider != "claude"
                or body.get("model") != attempt.model
                or body.get("stream") is not True
                or body.get("tools")
            ):
                raise ValueError("Unexpected SDK title request")
            message = json.dumps(body.get("messages"), ensure_ascii=False)
            if attempt.replay is None or not any(
                encoded_text(step.user_message) in message for step in attempt.replay.steps
            ):
                raise ValueError("SDK title does not belong to the declared conversation")
            if message in attempt.sdk_titles:
                raise ValueError("Duplicate SDK title request")
            attempt.sdk_titles.append(message)
            step = ResponseStep(
                provider="claude",
                model=attempt.model,
                fixture="text",
                user_message="",
                substitutions={
                    "message_id": f"msg_sdk_title_{attempt.id}",
                    "model": attempt.model,
                    "text": "Synthetic conversation",
                },
            )
            return 200, "text/event-stream", sse_frames(fixture_events(step))
        provider = (
            "claude"
            if path in {"/v1/messages", "/posthog_ai/v1/messages"}
            else "codex"
            if path in {"/v1/responses", "/posthog_ai/v1/responses"}
            else None
        )
        if provider is None or attempt.replay is None:
            raise ValueError(f"Unexpected provider endpoint {path}")
        index, frames = attempt.replay.respond(provider, body)

        def stream_response() -> Iterator[bytes]:
            # Open the SDK's SSE reader before pausing, so cancellation can abort a real streaming request.
            first, remainder = frames.split(b"\n\n", 1)
            yield first + b"\n\n"
            fault = attempt.faults["model"]
            if generation := fault.reach(str(index)):
                fault.wait_for_release(generation)
            fault.record("response_released", step=index, run_id=run_id)
            yield remainder

        return 200, "text/event-stream", stream_response()

    def control(self, method: str, path: str, body: dict[str, JsonValue]) -> JsonValue:
        if path == "health" and method == "GET":
            return {"ready": True}
        if path == "dispatcher/error":
            self.record_error(str(body["error"]))
            return {"ok": True}
        if path == "dispatcher/register":
            from products.tasks.backend.models import TaskRun

            attempt = self.attempt
            if attempt is None:
                raise ValueError("Dispatcher registration outside an attempt")
            run = TaskRun.objects.get(id=str(body["run_id"]), team_id=attempt.team.id)
            if attempt.task_id is not None and str(run.task_id) != attempt.task_id:
                raise ValueError("Dispatcher registration belongs to another task")
            attempt.task_id = str(run.task_id)
            attempt.run_id = str(run.id)
            attempt.workflow_id = str(body["workflow_id"])
            attempt.workflow_ids.append(attempt.workflow_id)
            attempt.dispatch_finished.clear()
            attempt.run_created.set()
            fault = attempt.faults["registration"]
            if generation := fault.reach(str(run.id)):
                fault.wait_for_release(generation)
            return {"attempt_id": attempt.id}
        if path == "attempt" and method == "POST":
            with self.lock:
                if self.attempt is not None:
                    raise ValueError("Only one active sandbox is allowed")
                self.attempt = Attempt(str(body["provider"]), self.output, surface=body.get("surface") is True)
                try:
                    self.attempt.seed()
                except Exception:
                    self.attempt = None
                    raise
                return self.attempt.public()
        attempt_id, operation = path.split("/", 1)
        attempt = self.require_attempt(attempt_id)
        if operation.startswith("dispatcher/"):
            if body.get("run_id") != attempt.run_id or body.get("workflow_id") != attempt.workflow_id:
                raise ValueError("Dispatcher observation belongs to another run")
            attempt.dispatch_finished.set()
            if operation == "dispatcher/registered":
                attempt.faults["registration"].record("registered", run_id=attempt.run_id)
                attempt.workflow_registered.set()
            elif operation == "dispatcher/failed":
                attempt.errors.append(f"Dispatcher registration failed: {body['error']}")
            else:
                raise ValueError("Unexpected dispatcher observation")
        elif operation == "configure":
            steps = body["steps"]
            if not isinstance(steps, list):
                raise ValueError("Expected response steps")
            attempt.configure([ResponseStep.model_validate(step) for step in steps])
        elif operation == "seed_editors":
            return attempt.seed_editors()
        elif operation.startswith("fault/"):
            _, name, action = operation.split("/")
            fault = attempt.faults[cast(FaultName, name)]
            if action == "arm":
                fault.arm(str(body["target"]) if "target" in body else None)
            elif action == "waitUntilReached":
                fault.wait_until_reached()
            elif action == "release":
                fault.release()
            elif action == "reset":
                fault.reset()
            else:
                raise ValueError("Unknown fault action")
        elif operation == "start":
            attempt.start(warm=body.get("warm", True) is True)
            return attempt.public()
        elif operation == "complete_run":
            attempt.complete_run()
        elif operation == "warm_resume":
            attempt.warm_resume()
            return attempt.public()
        elif operation.startswith("wait/"):
            events = {
                "registered": attempt.workflow_registered,
                "not_found": attempt.signal_not_found,
                "accepted": attempt.signal_accepted,
                "worker_ready": attempt.worker_ready,
            }
            if not events[operation.split("/")[1]].wait(60):
                raise TimeoutError(f"Barrier {operation} was not reached: {attempt.errors}")
        elif operation == "snapshot":
            from products.tasks.backend.models import Task, TaskRun

            attempt.insight.refresh_from_db()
            return {
                **attempt.snapshot(),
                "insight_name": attempt.insight.name,
                "task_count": Task.objects.filter(team=attempt.team).count(),
                "run_count": TaskRun.objects.filter(task__team=attempt.team).count(),
                "runs": [
                    {"status": status, "state": state}
                    for status, state in TaskRun.objects.filter(task__team=attempt.team).values_list("status", "state")
                ],
            }
        elif operation == "finish":
            try:
                attempt.errors.extend(self.errors)
                self.errors.clear()
                attempt.capture()
                attempt.verify()
                if self.errors:
                    raise AssertionError(self.errors)
            finally:
                attempt.cleanup()
                self.attempt = None
            if not attempt.surface:
                attempt.verify_proxy_ingest()
        else:
            raise ValueError(f"Unexpected controller operation {operation}")
        return {"ok": True}

    def finish_active_attempt(self) -> None:
        if self.attempt:
            try:
                self.attempt.capture()
            finally:
                self.attempt.cleanup()
                self.attempt = None

    def close(self) -> None:
        try:
            self.finish_active_attempt()
        finally:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=10)
