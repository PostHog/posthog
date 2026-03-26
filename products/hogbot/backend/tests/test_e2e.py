import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import requests
from django.test import LiveServerTestCase, override_settings

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.storage import object_storage

from products.hogbot.backend import gateway
from products.hogbot.backend import logic
from products.hogbot.backend.services.connection_token import get_sandbox_jwt_public_key
from products.hogbot.backend.tests.test_connection_token import TEST_RSA_PRIVATE_KEY

POSTHOG_ROOT = Path(__file__).resolve().parents[4]
HOGBOT_ROOT = POSTHOG_ROOT / "products" / "hogbot"
SERVER_DIST_BIN = HOGBOT_ROOT / "server" / "dist" / "bin.js"
TSUP_CLI = POSTHOG_ROOT.parent / "code" / "node_modules" / "tsup" / "dist" / "cli-default.js"
CODE_NODE_MODULES = POSTHOG_ROOT.parent / "code" / "node_modules"
SDK_FIXTURES = HOGBOT_ROOT / "server" / "src" / "__tests__" / "fixtures"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(predicate, timeout_seconds: float = 20.0, interval_seconds: float = 0.05) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval_seconds)
    raise AssertionError("Timed out waiting for condition")


@override_settings(
    SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY,
    OBJECT_STORAGE_ENABLED=True,
)
class TestHogbotServerEndToEnd(LiveServerTestCase):
    databases = {"default", "hogbot_db_writer"}

    @classmethod
    def setUpClass(cls):
        cls._build_server_dist()
        super().setUpClass()

    @classmethod
    def _build_server_dist(cls) -> None:
        subprocess.run(
            ["node", str(TSUP_CLI), "--config", "server/tsup.config.ts"],
            cwd=HOGBOT_ROOT,
            check=True,
            env={
                **os.environ,
                "NODE_PATH": str(CODE_NODE_MODULES),
            },
        )

    def setUp(self):
        super().setUp()
        get_sandbox_jwt_public_key.cache_clear()
        self.settings_override = self.settings(
            OBJECT_STORAGE_HOGBOT_FOLDER=f"test-hogbot-e2e-{self._testMethodName}",
        )
        self.settings_override.enable()

        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="hogbot-e2e@example.com", first_name="Hogbot", password="password")
        self.organization.members.add(self.user)
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

        self.api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Hogbot E2E",
            secure_value=hash_key_value(self.api_key),
            scopes=["*"],
        )

        self.workspace_dir = Path(tempfile.mkdtemp(prefix="hogbot-e2e-workspace-"))
        (self.workspace_dir / "sample.txt").write_text("workspace file", encoding="utf-8")

        self.deps_dir = Path(tempfile.mkdtemp(prefix="hogbot-e2e-deps-"))
        self._write_mock_sdk(self.deps_dir / "node_modules")
        self.register_path = self.deps_dir / "register-claude-sdk-mock.cjs"
        self.register_path.write_text(
            "\n".join(
                [
                    'const Module = require("module");',
                    'const path = require("path");',
                    "const originalLoad = Module._load;",
                    'const mockPath = path.join(__dirname, "node_modules", "@anthropic-ai", "claude-agent-sdk", "index.cjs");',
                    "Module._load = function patchedLoad(request, parent, isMain) {",
                    '    if (request === "@anthropic-ai/claude-agent-sdk") {',
                    "        return originalLoad(mockPath, parent, isMain);",
                    "    }",
                    "    return originalLoad(request, parent, isMain);",
                    "};",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.hogbot_port = find_free_port()
        self.hogbot_process = self._start_hogbot_server()
        wait_for(self._hogbot_health_is_ready)

    def tearDown(self):
        self._stop_hogbot_server()
        shutil.rmtree(self.workspace_dir, ignore_errors=True)
        shutil.rmtree(self.deps_dir, ignore_errors=True)
        self.settings_override.disable()
        get_sandbox_jwt_public_key.cache_clear()
        super().tearDown()

    def _write_mock_sdk(self, node_modules_dir: Path) -> None:
        package_dir = node_modules_dir / "@anthropic-ai" / "claude-agent-sdk"
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "package.json").write_text(
            json.dumps(
                {
                    "name": "@anthropic-ai/claude-agent-sdk",
                    "version": "0.0.0-test",
                    "main": "./index.cjs",
                    "exports": {
                        ".": {
                            "require": "./index.cjs",
                            "import": "./index.mjs",
                            "default": "./index.cjs",
                        }
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        shutil.copyfile(SDK_FIXTURES / "mock-claude-agent-sdk.cjs", package_dir / "index.cjs")
        shutil.copyfile(SDK_FIXTURES / "mock-claude-agent-sdk.mjs", package_dir / "index.mjs")

    def _start_hogbot_server(self) -> subprocess.Popen[str]:
        public_base_url = f"http://127.0.0.1:{self.hogbot_port}"
        env = {
            **os.environ,
            "JWT_PUBLIC_KEY": get_sandbox_jwt_public_key(),
            "POSTHOG_API_URL": self.live_server_url,
            "POSTHOG_PERSONAL_API_KEY": self.api_key,
            "NODE_PATH": str(CODE_NODE_MODULES),
            "NODE_OPTIONS": f"--require {self.register_path}",
        }
        process = subprocess.Popen(
            [
                "node",
                str(SERVER_DIST_BIN),
                "--port",
                str(self.hogbot_port),
                "--teamId",
                str(self.team.pk),
                "--workspacePath",
                str(self.workspace_dir),
                "--publicBaseUrl",
                public_base_url,
            ],
            cwd=HOGBOT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return process

    def _stop_hogbot_server(self) -> None:
        process = getattr(self, "hogbot_process", None)
        if not process:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        self.hogbot_process = None

    def _process_debug_output(self) -> str:
        process = self.hogbot_process
        assert process is not None
        stdout = process.stdout.read() if process.stdout else ""
        stderr = process.stderr.read() if process.stderr else ""
        return f"stdout:\n{stdout}\nstderr:\n{stderr}"

    def _request(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.api_key}"
        return requests.request(method, f"{self.live_server_url}{path}", headers=headers, timeout=20, **kwargs)

    def _hogbot_health_is_ready(self) -> bool:
        if self.hogbot_process.poll() is not None:
            raise AssertionError(f"hogbot-server exited early\n{self._process_debug_output()}")
        response = requests.get(f"http://127.0.0.1:{self.hogbot_port}/health", timeout=5)
        return response.status_code == 200

    def _wait_for_log_entry(self, path: str, method_name: str) -> list[dict]:
        payloads: list[dict] = []

        def has_entry() -> bool:
            response = self._request("GET", path)
            if response.status_code != 200:
                return False
            payloads.clear()
            content_type = response.headers.get("Content-Type", "")
            if content_type.startswith("text/plain"):
                for line in response.text.splitlines():
                    line = line.strip()
                    if line:
                        payloads.append(json.loads(line))
            else:
                payloads.extend(response.json())
            return any(entry.get("notification", {}).get("method") == method_name for entry in payloads)

        wait_for(has_entry)
        return payloads

    def _wait_for_object_storage_contains(self, key: str, needle: str) -> str:
        contents = ""

        def has_contents() -> bool:
            nonlocal contents
            contents = object_storage.read(key, missing_ok=True) or ""
            return needle in contents

        wait_for(has_contents)
        return contents

    def test_django_proxy_with_live_hogbot_server(self):
        connection = gateway.HogbotConnectionInfo(
            workflow_id=f"hogbot-team-{self.team.pk}",
            run_id="run-1",
            phase="running",
            ready=True,
            sandbox_id="sandbox-1",
            server_url=f"http://127.0.0.1:{self.hogbot_port}",
            connect_token=None,
            error=None,
        )

        with patch("products.hogbot.backend.api.gateway.get_hogbot_connection", return_value=connection):
            health = self._request("GET", f"/api/projects/{self.team.pk}/hogbot/health/")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(
                health.json(),
                {
                    "status": "ok",
                    "team_id": self.team.pk,
                    "busy": "none",
                    "active_signal_id": None,
                    "admin_ready": True,
                    "research_running": False,
                },
            )

            admin = self._request(
                "POST",
                f"/api/projects/{self.team.pk}/hogbot/send_message/",
                json={"content": "hello-through-django"},
            )
            self.assertEqual(admin.status_code, 200)
            self.assertEqual(admin.json(), {"response": "admin:hello-through-django"})

            admin_logs = self._wait_for_log_entry(
                f"/api/projects/{self.team.pk}/hogbot/admin/logs/?event_types=_hogbot/result",
                "_hogbot/result",
            )
            self.assertTrue(
                any(entry["notification"]["params"]["output"] == "admin:hello-through-django" for entry in admin_logs)
            )

            admin_key = logic.get_admin_log_key(self.team.pk)
            admin_object = self._wait_for_object_storage_contains(admin_key, "admin:hello-through-django")
            self.assertIn("_hogbot/result", admin_object)

            slow_thread_response = {}

            def send_slow_admin() -> None:
                try:
                    slow_thread_response["response"] = self._request(
                        "POST",
                        f"/api/projects/{self.team.pk}/hogbot/send_message/",
                        json={"content": "slow-admin"},
                    )
                except Exception as error:
                    slow_thread_response["error"] = error

            thread = threading.Thread(target=send_slow_admin)
            thread.start()
            wait_for(
                lambda: self._request("GET", f"/api/projects/{self.team.pk}/hogbot/health/").json().get("busy") == "admin"
            )

            cancel = self._request("POST", f"/api/projects/{self.team.pk}/hogbot/cancel/", json={})
            self.assertEqual(cancel.status_code, 200)
            self.assertEqual(cancel.json(), {"cancelled": True})

            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
            self.assertNotIn("error", slow_thread_response)
            cancelled = slow_thread_response["response"]
            self.assertEqual(cancelled.status_code, 409)
            self.assertEqual(cancelled.json(), {"error": "Admin request cancelled"})

            logs_response = self._request(
                "GET",
                f"/api/projects/{self.team.pk}/hogbot/logs/?scope=research&signal_id=sig-live",
                stream=True,
            )
            self.assertEqual(logs_response.status_code, 200)

            research = self._request(
                "POST",
                f"/api/projects/{self.team.pk}/hogbot/research/",
                json={"signal_id": "sig-live", "prompt": "slow-research"},
            )
            self.assertEqual(research.status_code, 202)
            self.assertEqual(research.json(), {"status": "started", "signal_id": "sig-live"})

            seen_result = False
            for raw_line in logs_response.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith("data: "):
                    continue
                event = json.loads(raw_line[6:])
                if event.get("notification", {}).get("method") == "_hogbot/result":
                    self.assertEqual(event["notification"]["params"]["output"], "research:slow-research")
                    seen_result = True
                    break
            logs_response.close()
            self.assertTrue(seen_result)

            research_logs = self._wait_for_log_entry(
                f"/api/projects/{self.team.pk}/hogbot/research/sig-live/logs/?event_types=_hogbot/result",
                "_hogbot/result",
            )
            self.assertTrue(
                any(entry["notification"]["params"]["output"] == "research:slow-research" for entry in research_logs)
            )

            research_key = logic.get_research_log_key(self.team.pk, "sig-live")
            research_object = self._wait_for_object_storage_contains(research_key, "research:slow-research")
            self.assertIn("_hogbot/result", research_object)

            post_research_admin = self._request(
                "POST",
                f"/api/projects/{self.team.pk}/hogbot/send_message/",
                json={"content": "after-research"},
            )
            self.assertEqual(post_research_admin.status_code, 200)
            self.assertEqual(post_research_admin.json(), {"response": "admin:after-research"})

            filesystem = self._request(
                "GET",
                f"/api/projects/{self.team.pk}/hogbot/filesystem/content/",
                params={"path": "/sample.txt"},
            )
            self.assertEqual(filesystem.status_code, 200)
            self.assertEqual(filesystem.json()["content"], "workspace file")
