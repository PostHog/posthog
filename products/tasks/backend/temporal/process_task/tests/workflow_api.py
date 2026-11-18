import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def main() -> None:
    payload = json.loads(Path("/tmp/workflow-api.json").read_text())
    task = payload["task"]
    run = payload["run"]
    task_path = f"/api/projects/{task['team_id']}/tasks/{task['id']}/"
    run_path = f"{task_path}runs/{run['id']}/"

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self) -> bool:
            if self.headers.get("Authorization") == f"Bearer {os.environ['POSTHOG_PERSONAL_API_KEY']}":
                return True
            self.respond(403, {"detail": "Invalid test credential"})
            return False

        def do_GET(self) -> None:
            if self.path == "/health":
                self.respond(200, {"ready": True})
            elif self.authorized():
                if self.path == task_path:
                    self.respond(200, task)
                elif self.path == run_path:
                    self.respond(200, run)
                elif self.path == "/api/users/@me/":
                    self.respond(200, {"id": 1, "distinct_id": "workflow-test-user"})
                else:
                    self.respond(404, {"detail": "Unexpected test API request"})

        def do_POST(self) -> None:
            if self.authorized():
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path == f"{run_path}append_log/":
                    self.respond(200, run)
                else:
                    self.respond(404, {"detail": "Unexpected test API request"})

        def do_PATCH(self) -> None:
            if self.authorized():
                update = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if self.path == run_path:
                    run.update(update)
                    self.respond(200, run)
                else:
                    self.respond(404, {"detail": "Unexpected test API request"})

    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()


if __name__ == "__main__":
    main()
