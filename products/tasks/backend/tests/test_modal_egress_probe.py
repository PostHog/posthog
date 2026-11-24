import sys
import json
import selectors
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from modal.exception import NotFoundError, SandboxFilesystemNotFoundError, ServiceError
from parameterized import parameterized

from products.tasks.backend.logic.services.modal_egress_probe import (
    _PREPARE_IDENTITY,
    _RELAY_RUNNING,
    _RENEW_CERTIFICATE,
    _START_RELAY,
    _WAIT_READY,
    AgentEgressCertificateDeliveryError,
    ModalEgressProbe,
)
from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import SandboxTemplate


@override_settings(DEBUG=True, TEST=True, SANDBOX_PROVIDER="MODAL_DOCKER")
class TestModalEgressProbe(SimpleTestCase):
    def setUp(self) -> None:
        self.sandbox = MagicMock(spec=ModalSandbox)
        self.sandbox._sandbox = MagicMock()
        self.sandbox._sandbox.object_id = "sb-original"
        self.sandbox._sandbox.poll.return_value = None
        self.sidecar = self.sandbox._sandbox._experimental_sidecars.create.return_value
        self.sidecar.object_id = "sc-original"
        self.sidecar.poll.return_value = None
        self.sandbox._sandbox._experimental_sidecars.get.side_effect = NotFoundError("missing")
        process = self.sidecar.exec.return_value
        process.returncode = 0
        process.stdout.read.return_value = ""
        self.sandbox._sandbox.exec.return_value.returncode = 0
        self.factory = self.enterContext(
            patch(
                "products.tasks.backend.logic.services.modal_egress_probe.get_sandbox_class_for_run_backend",
                return_value=ModalSandbox,
            )
        )
        self.create = self.enterContext(patch.object(ModalSandbox, "create", return_value=self.sandbox))
        self.lookup = self.enterContext(
            patch(
                "products.tasks.backend.logic.services.modal_egress_probe.modal.Sandbox.from_name",
                side_effect=NotFoundError("missing"),
            )
        )
        self.lookup_id = self.enterContext(
            patch(
                "products.tasks.backend.logic.services.modal_egress_probe.modal.Sandbox.from_id",
                return_value=self.sandbox._sandbox,
            )
        )
        self.enterContext(patch.object(ModalSandbox, "_get_app_for_config"))
        self.enterContext(patch("products.tasks.backend.logic.services.modal_egress_probe.modal.Image.from_id"))

    def launch(
        self, endpoint: str = "https://run-a.egress.example.com", dev_proxy_ipv4: str | None = None
    ) -> ModalEgressProbe:
        return ModalEgressProbe.create(
            name="test-egress", relay_image_id="im-example", endpoint=endpoint, dev_proxy_ipv4=dev_proxy_ipv4
        )

    @parameterized.expand(
        [
            ("development", "run-a.egress.example.com"),
            ("staging", "run-a.egress.example.com"),
            ("double_hyphen", "run-a.edge--blue.example.com"),
            ("punycode", "run-a.xn--bcher-kva.example.com"),
        ]
    )
    def test_launch_uses_isolated_probe_profile_and_exact_sidecar_destination(
        self, environment: str, hostname: str
    ) -> None:
        if environment == "staging":
            self.enterContext(
                override_settings(
                    DEBUG=False,
                    TEST=False,
                    CLOUD_DEPLOYMENT="DEV",
                    SANDBOX_PROVIDER="modal",
                    AGENT_EGRESS_STAGING_PROBE_RUN_ID="00000000-0000-4000-8000-000000000001",
                )
            )
        probe = self.launch(endpoint=f"https://{hostname}")

        config = self.create.call_args.args[0]
        self.assertEqual(config.template, SandboxTemplate.SLIM_BASE)
        self.assertTrue(config.agent_egress_probe)
        self.assertTrue(config.vm_runtime)
        self.assertIsNone(config.environment_variables)
        policy = self.sandbox._sandbox._experimental_sidecars.create.call_args.kwargs
        self.assertEqual(policy["outbound_domain_allowlist"], [hostname])
        self.assertIsNone(policy["outbound_cidr_allowlist"])
        self.assertNotIn("volumes", policy)
        self.assertNotIn("secrets", policy)
        self.assertEqual(policy["experimental_memory_reserve_consume_mib"], 1024)
        self.sidecar.filesystem.read_text.return_value = "public CSR"
        self.assertEqual(probe.certificate_request(), "public CSR")
        self.sidecar.filesystem.read_text.assert_called_once_with("/run/egress/relay.csr")

    def test_dev_transport_is_limited_to_one_public_ip(self) -> None:
        self.launch(endpoint="https://run-a.egress.example.com:23456", dev_proxy_ipv4="1.1.1.1")

        policy = self.sandbox._sandbox._experimental_sidecars.create.call_args.kwargs
        self.assertEqual(policy["outbound_cidr_allowlist"], ["1.1.1.1/32"])
        self.assertIsNone(policy["outbound_domain_allowlist"])

    @parameterized.expand(
        [
            ("http://run-a.egress.example.com", None),
            ("https://RUN-A.egress.example.com", None),
            ("https://run-a.-edge.example.com", None),
            ("https://run-a.edge-.example.com", None),
            ("https://run-a." + "a" * 64 + ".example.com", None),
            ("https://run-a.egress.example.com/path", None),
            ("https://run-a.egress.example.com?key=value", None),
            ("https://user:password@run-a.egress.example.com", None),
            ("https://run-a.egress.example.com:8443", None),
            ("https://run-a.egress.example.com", "127.0.0.1"),
            ("https://run-a.egress.example.com", "10.0.0.1"),
        ]
    )
    def test_invalid_destination_cannot_create_sandbox(self, endpoint: str, dev_proxy_ipv4: str | None) -> None:
        with self.assertRaises(ValueError):
            self.launch(endpoint=endpoint, dev_proxy_ipv4=dev_proxy_ipv4)
        self.create.assert_not_called()

    @parameterized.expand([(False, False, "MODAL_DOCKER"), (True, True, "modal"), (True, True, "docker")])
    def test_requires_development_modal_provider(self, debug: bool, test: bool, provider: str) -> None:
        with override_settings(DEBUG=debug, TEST=test, SANDBOX_PROVIDER=provider):
            with self.assertRaises(RuntimeError):
                self.launch()
        self.create.assert_not_called()

    def test_failed_key_generation_can_resume_same_sandbox_and_relay(self) -> None:
        self.sidecar.exec.return_value.returncode = 1

        with self.assertRaises(RuntimeError):
            self.launch()

        self.sandbox.destroy.assert_not_called()
        self.lookup.side_effect = None
        self.lookup.return_value = self.sandbox._sandbox
        self.sandbox._sandbox._experimental_sidecars.get.side_effect = None
        self.sandbox._sandbox._experimental_sidecars.get.return_value = self.sidecar
        self.sidecar.exec.return_value.returncode = 0

        probe = self.launch()

        self.assertEqual(probe.sandbox.id, "sb-original")
        self.assertEqual(probe.sidecar.object_id, "sc-original")
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual(self.sandbox._sandbox._experimental_sidecars.create.call_count, 1)

    @parameterized.expand([("sandbox",), ("sidecar",)])
    def test_ended_execution_cannot_recreate_provider_resources(self, ended: str) -> None:
        self.lookup.side_effect = None
        self.lookup.return_value = self.sandbox._sandbox
        self.sandbox._sandbox._experimental_sidecars.get.side_effect = None
        self.sandbox._sandbox._experimental_sidecars.get.return_value = self.sidecar
        target = self.sandbox._sandbox if ended == "sandbox" else self.sidecar
        target.poll.return_value = 0

        with self.assertRaises(ValueError):
            self.launch()

        self.create.assert_not_called()
        self.sandbox._sandbox._experimental_sidecars.create.assert_not_called()

    @parameterized.expand([("sandbox",), ("sidecar",)])
    def test_provider_lookup_outage_cannot_create_a_replacement(self, failed: str) -> None:
        target = self.lookup if failed == "sandbox" else self.sandbox._sandbox._experimental_sidecars.get
        target.side_effect = ServiceError("unavailable")

        with self.assertRaises(ServiceError):
            self.launch()

        if failed == "sandbox":
            self.create.assert_not_called()
        self.sandbox._sandbox._experimental_sidecars.create.assert_not_called()

    @parameterized.expand([("missing",), ("replaced",), ("ended",), ("unavailable",)])
    def test_reconnect_refuses_changed_or_unavailable_relay(self, state: str) -> None:
        lookup = self.sandbox._sandbox._experimental_sidecars.get
        lookup.side_effect = None
        lookup.return_value = self.sidecar
        error: type[Exception] = ValueError
        if state == "missing":
            lookup.side_effect = NotFoundError("missing")
        elif state == "replaced":
            self.sidecar.object_id = "sc-replacement"
        elif state == "ended":
            self.sidecar.poll.return_value = 0
        else:
            lookup.side_effect = ServiceError("unavailable")
            error = ServiceError

        with self.assertRaises(error):
            ModalEgressProbe.connect(
                sandbox_id="sb-original",
                sidecar_id="sc-original",
                endpoint="https://run-a.egress.example.com",
                ttl_seconds=900,
            )

        self.sandbox._sandbox._experimental_sidecars.create.assert_not_called()

    @parameterized.expand(
        [
            ("name", "missing"),
            ("name", "ended"),
            ("name", "live"),
            ("name", "unavailable"),
            ("id", "missing"),
            ("id", "ended"),
            ("id", "live"),
            ("id", "unavailable"),
            ("name", "live", "staging"),
            ("id", "live", "staging"),
        ]
    )
    def test_cleanup_distinguishes_missing_sandbox_from_outage(
        self, reference: str, state: str, environment: str = "development"
    ) -> None:
        if environment == "staging":
            self.enterContext(
                override_settings(
                    DEBUG=False,
                    TEST=False,
                    CLOUD_DEPLOYMENT="DEV",
                    SANDBOX_PROVIDER="modal",
                    AGENT_EGRESS_STAGING_PROBE_RUN_ID="",
                )
            )
            with self.assertRaises(RuntimeError):
                self.launch()
        lookup = self.lookup if reference == "name" else self.lookup_id
        lookup.side_effect = None
        lookup.return_value = self.sandbox._sandbox
        if state == "missing":
            lookup.side_effect = NotFoundError("missing")
        elif state == "ended":
            self.sandbox._sandbox.poll.return_value = 0
        elif state == "unavailable":
            lookup.side_effect = ServiceError("unavailable")
        close = ModalEgressProbe.close_named if reference == "name" else ModalEgressProbe.close_sandbox

        if state == "unavailable":
            with self.assertRaises(ServiceError):
                close("test-egress")
        else:
            close("test-egress")

        self.assertEqual(self.sandbox._sandbox.terminate.call_count, int(state == "live"))

    def test_attached_relay_process_uses_the_remaining_sandbox_lifetime(self) -> None:
        with patch("products.tasks.backend.logic.services.modal_egress_probe.MAX_SANDBOX_TTL_SECONDS", 21600):
            probe = ModalEgressProbe.attach(
                sandbox_id="sb-original",
                relay_name="egress-relay-example",
                relay_image_id="im-example",
                endpoint="https://run-a.egress.example.com",
                ttl_seconds=7200,
            )
        probe.start_relay(certificate="public certificate", server_ca="public CA")
        start = next(call for call in self.sidecar.exec.call_args_list if _START_RELAY in call.args)
        self.assertEqual(start.kwargs["timeout"], 7200)
        self.create.assert_not_called()
        with self.assertRaisesRegex(ValueError, "lifetime"):
            ModalEgressProbe.create(
                name="test-egress",
                relay_image_id="im-example",
                endpoint="https://run-a.egress.example.com",
                ttl_seconds=7200,
            )

    @parameterized.expand([("write",), ("reload",)])
    def test_certificate_delivery_errors_are_distinct_from_authority_errors(self, phase: str) -> None:
        probe = self.launch()
        if phase == "write":
            self.sidecar.filesystem.write_text.side_effect = ServiceError("temporarily unavailable")
        else:
            self.sidecar.exec.return_value.returncode = 1
        with self.assertRaisesRegex(AgentEgressCertificateDeliveryError, "certificate delivery failed"):
            probe.renew_certificate("public certificate")

    @parameterized.expand([(False,), (True,)])
    def test_identity_recovery_preserves_private_key(self, csr_missing: bool) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            command = [sys.executable, "-c", _PREPARE_IDENTITY, temporary]
            subprocess.run(command, check=True)
            key = (directory / "relay-key.pem").read_bytes()
            csr = (directory / "relay.csr").read_bytes()
            if csr_missing:
                (directory / "relay.csr").unlink()
                (directory / "relay.tmp").write_text("interrupted write")

            subprocess.run(command, check=True)

            self.assertEqual((directory / "relay-key.pem").read_bytes(), key)
            self.assertEqual((directory / "relay.csr").read_bytes(), csr)
            self.assertEqual((directory / "relay-key.pem").stat().st_mode & 0o777, 0o600)

    def test_relay_restart_preserves_running_process(self) -> None:
        with TemporaryDirectory() as temporary:
            command = [
                sys.executable,
                "-c",
                _START_RELAY,
                temporary,
                sys.executable,
                "-c",
                'import sys; print("ready", flush=True); sys.stdin.read()',
            ]
            with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as running:
                try:
                    assert running.stdout is not None
                    with selectors.DefaultSelector() as selector:
                        selector.register(running.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=5))
                    self.assertEqual(running.stdout.readline(), "ready\n")
                    status = subprocess.run(
                        [sys.executable, "-c", _RELAY_RUNNING, temporary],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=True,
                    )
                    self.assertEqual(status.stdout, "running\n")

                    duplicate = subprocess.run(command, input="", capture_output=True, text=True, timeout=5, check=True)

                    self.assertEqual(duplicate.stdout, "")
                    self.assertIsNone(running.poll())
                finally:
                    running.communicate(timeout=5)

            status = subprocess.run(
                [sys.executable, "-c", _RELAY_RUNNING, temporary],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            self.assertEqual(status.stdout, "")
            restarted = subprocess.run(command, input="", capture_output=True, text=True, timeout=5, check=True)
            self.assertEqual(restarted.stdout, "ready\n")

    @parameterized.expand([("accepted",), ("rejected",), ("stale_process",)])
    def test_certificate_delivery_waits_for_reload_and_preserves_failed_material(self, outcome: str) -> None:
        server = """
import json, signal, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
directory = Path(sys.argv[1])
counts = {'success': 0, 'failure': 0}
def reload(_signal, _frame):
    material = (directory / 'relay.pem').read_text()
    if material == 'rejected':
        counts['failure'] += 1
    else:
        (directory / 'active.pem').write_text(material)
        counts['success'] += 1
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(''.join(
            'egress_reload_total{outcome="' + key + '"} ' + str(value) + '\\n'
            for key, value in counts.items()
        ).encode())
    def log_message(self, *args):
        pass
signal.signal(signal.SIGHUP, reload)
with HTTPServer(('127.0.0.1', 0), Handler) as server:
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01))
    thread.start()
    print(server.server_port, flush=True)
    sys.stdin.read()
    server.shutdown()
    thread.join()
"""
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            certificate = directory / "relay.pem"
            certificate.write_text("original")
            (directory / "active.pem").write_text("original")
            command = [sys.executable, "-c", _START_RELAY, temporary, sys.executable, "-c", server, temporary]
            with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as running:
                try:
                    assert running.stdout is not None
                    with selectors.DefaultSelector() as selector:
                        selector.register(running.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=5))
                    port = int(running.stdout.readline())
                    if outcome == "stale_process":
                        identity_file = directory / "relay-process.json"
                        identity = json.loads(identity_file.read_text())
                        identity_file.write_text(json.dumps({**identity, "start_time": "0"}))
                    candidate = directory / "candidate.pem"
                    candidate.write_text("rejected" if outcome == "rejected" else "renewed")
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            _RENEW_CERTIFICATE,
                            temporary,
                            str(candidate),
                            f"http://127.0.0.1:{port}/metrics",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=8,
                    )

                    self.assertEqual(result.returncode == 0, outcome == "accepted", result.stderr)
                    expected = "renewed" if outcome == "accepted" else "original"
                    self.assertEqual(certificate.read_text(), expected)
                    self.assertEqual((directory / "active.pem").read_text(), expected)
                    self.assertFalse(candidate.exists())
                    self.assertIsNone(running.poll())
                finally:
                    running.communicate(timeout=5)

    @parameterized.expand([(None,), ("public enrollment CA",)])
    def test_start_relay_installs_only_public_enrollment_material(self, client_ca: str | None) -> None:
        probe = self.launch()
        probe.start_relay(certificate="public relay certificate", server_ca="public server CA", client_ca=client_ca)

        files = {call.args[1]: call.args[0] for call in self.sidecar.filesystem.write_text.call_args_list}
        configuration = json.loads(files["/run/egress/relay.json"])
        if client_ca is None:
            self.assertNotIn("client_ca_file", configuration)
        else:
            self.assertEqual(files[configuration["client_ca_file"]], client_ca)
        self.assertEqual(files[configuration["certificate_file"]], "public relay certificate")
        self.assertNotIn(configuration["private_key_file"], files)

    @parameterized.expand(
        [("live",), ("enrollment",), ("missing",), ("ended",), ("removed",), ("delete_failed",), ("lookup_failed",)]
    )
    def test_attached_relay_cleanup_keeps_main_sandbox_and_other_relays(self, state: str) -> None:
        if state == "enrollment":
            self.enterContext(
                override_settings(
                    DEBUG=False,
                    TEST=False,
                    CLOUD_DEPLOYMENT="DEV",
                    SANDBOX_PROVIDER="modal",
                    AGENT_EGRESS_ENROLLMENT_CONFIG="/run/egress/enrollment.json",
                )
            )
        relay_name = "egress-relay-first"
        probe = ModalEgressProbe.attach(
            sandbox_id="sb-original",
            relay_name=relay_name,
            relay_image_id="im-example",
            endpoint="https://run-a.egress.example.com",
            ttl_seconds=900,
        )
        if state == "enrollment":
            self.enterContext(override_settings(AGENT_EGRESS_ENROLLMENT_CONFIG=""))
        self.sandbox._sandbox._experimental_sidecars.get.side_effect = None
        self.sandbox._sandbox._experimental_sidecars.get.return_value = self.sidecar
        self.sandbox._sandbox.exec.return_value.stdout.read.return_value = '{"204": 1}'

        self.assertEqual(probe.probe(), {204: 1})
        self.assertEqual(self.sandbox._sandbox.exec.call_args.args[-2:], (relay_name, probe.capability_path))
        replacement_path = "/run/posthog/egress-capability.egress-relay-second"
        files = {probe.capability_path: "synthetic-first", replacement_path: "synthetic-replacement"}
        alive = state not in {"missing", "ended"}

        def terminate() -> None:
            nonlocal alive
            alive = False

        def remove(path: str) -> None:
            if state == "delete_failed":
                raise ServiceError("unavailable")
            try:
                del files[path]
            except KeyError:
                raise SandboxFilesystemNotFoundError("missing") from None

        self.sidecar.terminate.side_effect = terminate
        self.sidecar.poll.side_effect = lambda: None if alive else 0
        self.sandbox._sandbox.filesystem.remove.side_effect = remove
        if state == "missing":
            self.sandbox._sandbox._experimental_sidecars.get.side_effect = NotFoundError("missing")
        elif state == "lookup_failed":
            self.sandbox._sandbox._experimental_sidecars.get.side_effect = ServiceError("unavailable")
        elif state == "removed":
            del files[probe.capability_path]

        if state in {"delete_failed", "lookup_failed"}:
            with self.assertRaises(ServiceError):
                ModalEgressProbe.close_relay("sb-original", relay_name)
            self.assertIn(probe.capability_path, files)
        else:
            ModalEgressProbe.close_relay("sb-original", relay_name)
            self.assertNotIn(probe.capability_path, files)

        self.assertEqual(alive, state == "lookup_failed")
        self.assertEqual(files[replacement_path], "synthetic-replacement")
        self.sandbox._sandbox.terminate.assert_not_called()
        self.sandbox._sandbox._experimental_sidecars.get.assert_called_with(name=relay_name, include_terminated=True)

    def test_cleanup_rejects_invalid_relay_name_before_provider_access(self) -> None:
        with self.assertRaises(ValueError):
            ModalEgressProbe.close_relay("sb-original", "../../egress-relay-second")

        self.lookup_id.assert_not_called()

    def test_attached_executions_deliver_separate_capability_files(self) -> None:
        paths = []
        for relay_name in ("egress-relay-first", "egress-relay-second"):
            probe = ModalEgressProbe.attach(
                sandbox_id="sb-original",
                relay_name=relay_name,
                relay_image_id="im-example",
                endpoint="https://run-a.egress.example.com",
                ttl_seconds=900,
            )
            probe.publish_capability("synthetic-capability")
            paths.append(self.sandbox._sandbox.exec.call_args.args[-1])

        self.assertEqual(
            paths,
            ["/run/posthog/egress-capability.egress-relay-first", "/run/posthog/egress-capability.egress-relay-second"],
        )

    def test_capability_delivery_replaces_file_without_environment_update(self) -> None:
        probe = self.launch()
        probe.publish_capability("synthetic-capability")

        value, path = self.sandbox._sandbox.filesystem.write_text.call_args.args
        self.assertEqual(value, "synthetic-capability")
        self.assertTrue(path.startswith("/run/posthog/egress-capability."))
        replacement = self.sandbox._sandbox.exec.call_args
        self.assertIn("os.replace", replacement.args[2])
        self.assertEqual(replacement.args[-2:], (path, "/run/posthog/egress-capability"))
        self.assertNotIn("env", replacement.kwargs)

    def test_probe_reports_status_counts_without_request_data(self) -> None:
        probe = self.launch()
        self.sandbox._sandbox.exec.return_value.stdout.read.return_value = '{"204": 31, "503": 1}'

        self.assertEqual(probe.probe(count=32, concurrency=8), {204: 31, 503: 1})

        with self.assertRaises(ValueError):
            probe.probe(count=1001)
        with self.assertRaises(ValueError):
            probe.probe(concurrency=33)

    def test_readiness_accepts_runtime_no_content_response(self) -> None:
        with patch("urllib.request.urlopen") as request, patch("time.sleep") as sleep:
            request.return_value.__enter__.return_value.status = 204
            exec(_WAIT_READY)

        request.assert_called_once()
        sleep.assert_not_called()

    def test_readiness_deadline_includes_request_time(self) -> None:
        elapsed = 0.0

        def advance(seconds: float) -> None:
            nonlocal elapsed
            elapsed += seconds

        def unavailable(url: str, *, timeout: float) -> None:
            advance(timeout)
            raise TimeoutError

        with (
            patch("time.monotonic", side_effect=lambda: elapsed),
            patch("time.sleep", side_effect=advance),
            patch("urllib.request.urlopen", side_effect=unavailable),
        ):
            with self.assertRaises(SystemExit) as failure:
                exec(_WAIT_READY)

        self.assertEqual(failure.exception.code, 1)
        self.assertAlmostEqual(elapsed, 20)

    @parameterized.expand(
        [
            ("{}",),
            ('{"204": 0}',),
            ('{"204": true}',),
            ('{"204": -1}',),
            ('{"204": 2}',),
            ('{"204": 1, "503": 1}',),
            ('{"999": 1}',),
            ("not json",),
        ]
    )
    def test_probe_rejects_invalid_or_incomplete_status_counts(self, output: str) -> None:
        probe = self.launch()
        self.sandbox._sandbox.exec.return_value.stdout.read.return_value = output

        with self.assertRaises(RuntimeError):
            probe.probe()
