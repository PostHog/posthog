from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import yaml
from hogbox_preview.backend import ExecResult, PreviewBackend
from hogbox_preview.desktop_profile import DESKTOP_PREVIEW_IMAGES
from hogbox_preview.stack import PostHogPreviewStack


def _mapping_without_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise AssertionError(f"Compose refuses a duplicate key: {key!r} at {key_node.start_mark}")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


def _tagged_value(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return _mapping_without_duplicates(loader, node)
    return node.value


# Parses the override the way Compose does: duplicate mapping keys are an error,
# and Compose's own !override / !reset tags are values, not YAML core types.
class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates)
ComposeLoader.add_multi_constructor("!", _tagged_value)


class DesktopProfileStack(unittest.TestCase):
    def test_desktop_profile_adds_oauth_seed_gateway_and_readiness(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.web_url = "https://preview.example.com/"
        backend.run_long.return_value = ExecResult(0, "DESKTOP_SEED_OK", "")

        # The readiness script's stdout carries the token + project the gateway
        # probe reuses; the probe's curl returns its HTTP code as stdout.
        def exec_by_command(command: str, *args: object, **kwargs: object) -> ExecResult:
            if "count_tokens" in command:
                return ExecResult(0, "400", "")
            if "desktop-readiness" in command:
                return ExecResult(
                    0, "DESKTOP_READY_TOKEN=fake-preview-token\nDESKTOP_READY_PROJECT=7\nDESKTOP_READY_OK", ""
                )
            return ExecResult(0, "DEEP_HEALTH_OK", "")

        backend.exec.side_effect = exec_by_command
        stack = PostHogPreviewStack(
            backend,
            branch="1" * 40,
            seed_demo_data=False,
            desktop_pr_number=123,
        )
        url = stack.bring_up()
        files = {call.args[0]: call.args[1] for call in backend.write_file.call_args_list}
        override = files["/home/hog/posthog/docker-compose.preview.yml"]
        self.assertIn("DESKTOP_PREVIEW=1", override)
        self.assertIn("handle_path /llm-gateway/*", override)
        self.assertIn("header_up x-posthog-provider bedrock", override)
        self.assertIn("AWS_CONTAINER_CREDENTIALS_FULL_URI=http://127.0.0.1:8181/credentials", override)
        self.assertEqual(override.count("network_mode: host"), 2)
        # The whole file has to parse: a second web key, or a stray indent in the
        # generated proxy block, makes Compose refuse it before any merge runs.
        services = yaml.load(override, Loader=ComposeLoader)["services"]
        self.assertEqual(services["web"]["ports"], ["8001:8000"])
        self.assertLessEqual({"desktop-preview-proxy", "llm-gateway"}, set(services))
        # The gateway reads only the LLM_GATEWAY_-prefixed env names.
        self.assertIn("LLM_GATEWAY_POSTHOG_API_BASE_URL=http://localhost:8001", override)
        self.assertNotIn("POSTHOG_API_BASE_URL=http", override.replace("LLM_GATEWAY_POSTHOG_API_BASE_URL", ""))
        # The seed pins the application UUID the gateway allowlist expects.
        seed_script = files["/home/hog/posthog/desktop-oauth-seed.py"]
        self.assertIn("019ebb47-c750-0000-e1ea-723a6ff112d3", seed_script)
        commands = [call.args[0] for call in backend.run_long.call_args_list]
        self.assertLess(
            commands.index(next(c for c in commands if "up -d --no-build web" in c)),
            commands.index(next(c for c in commands if "desktop-preview-proxy llm-gateway" in c)),
        )
        backend.wait_http_ok.assert_any_call("/llm-gateway/_liveness", expect=200, timeout=600)
        self.assertEqual(stack.desktop_gateway_url(url), "https://preview.example.com/llm-gateway")
        checkout = next(command for command in commands if "fetch --depth" in command)
        self.assertIn("origin " + "1" * 40, checkout)
        seed = next(command for command in commands if "manage.py shell" in command)
        self.assertIn("< /home/hog/posthog/desktop-oauth-seed.py", seed)

    def test_readiness_surfaces_guest_failures(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.exec.return_value = ExecResult(1, "", "Desktop access denied")
        stack = PostHogPreviewStack(backend, desktop_pr_number=123)
        with self.assertRaisesRegex(RuntimeError, "Desktop access denied"):
            stack._run_desktop_readiness(123)

    def test_gateway_wait_timeout_dumps_container_diagnostics(self) -> None:
        # Both containers are restart: always, so a bad Caddyfile crash-loops
        # instead of exiting and the wait reports only a status code.
        backend = MagicMock(spec=PreviewBackend)
        backend.web_port = 8000
        backend.exec.return_value = ExecResult(0, "DESKTOP_READY_OK", "")
        backend.wait_http_ok.side_effect = TimeoutError("never returned 200 (last=502)")
        stack = PostHogPreviewStack(backend, desktop_pr_number=123)

        with self.assertRaisesRegex(TimeoutError, "never returned 200"):
            stack._run_desktop_readiness(123)

        collected = [call.args[0] for call in backend.exec.call_args_list]
        self.assertIn(stack._compose("ps"), collected)
        for service in ("desktop-preview-proxy", "llm-gateway"):
            self.assertTrue(any(f"logs --tail 40 {service}" in command for command in collected))


class DesktopImagePull(unittest.TestCase):
    # These two are not in the golden, so every preview fetches them cold from
    # ghcr, which flakes mid-layer. pull_image() covers the images it owns; a
    # simplification back to a bare `compose up` would silently lose these.
    def test_retries_each_desktop_image_independently(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.run_long.side_effect = [
            RuntimeError("proxy TLS timeout"),
            None,
            RuntimeError("gateway TLS timeout"),
            None,
            None,
        ]
        stack = PostHogPreviewStack(backend, desktop_pr_number=123)

        stack._up_desktop_services()

        commands = [call.args[0] for call in backend.run_long.call_args_list]
        self.assertEqual(
            [command for command in commands if command.startswith("docker pull")],
            [f"docker pull {image}" for image in DESKTOP_PREVIEW_IMAGES for _ in range(2)],
        )
        self.assertIn("up -d --no-build desktop-preview-proxy llm-gateway", commands[-1])

    def test_exhausted_pull_stops_before_compose_up(self) -> None:
        backend = MagicMock(spec=PreviewBackend)
        backend.run_long.side_effect = RuntimeError("TLS timeout")
        stack = PostHogPreviewStack(backend, desktop_pr_number=123)
        first = DESKTOP_PREVIEW_IMAGES[0]

        with self.assertRaisesRegex(RuntimeError, f"docker pull {first} failed after 3 attempts: TLS timeout"):
            stack._up_desktop_services()

        self.assertEqual(
            [call.args[0] for call in backend.run_long.call_args_list],
            [f"docker pull {first}"] * 3,
        )


if __name__ == "__main__":
    unittest.main()
