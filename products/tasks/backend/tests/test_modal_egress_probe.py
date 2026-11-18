from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.tasks.backend.logic.services.modal_egress_probe import _WAIT_READY, ModalEgressProbe
from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.sandbox import SandboxTemplate


@override_settings(DEBUG=True, TEST=True, SANDBOX_PROVIDER="MODAL_DOCKER")
class TestModalEgressProbe(SimpleTestCase):
    def setUp(self) -> None:
        self.sandbox = MagicMock(spec=ModalSandbox)
        self.sandbox._sandbox = MagicMock()
        self.sidecar = self.sandbox._sandbox._experimental_sidecars.create.return_value
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
        self.enterContext(patch("products.tasks.backend.logic.services.modal_egress_probe.modal.Image.from_id"))

    def launch(
        self, endpoint: str = "https://run-a.egress.example.com", dev_proxy_ipv4: str | None = None
    ) -> ModalEgressProbe:
        return ModalEgressProbe.create(
            name="test-egress", relay_image_id="im-example", endpoint=endpoint, dev_proxy_ipv4=dev_proxy_ipv4
        )

    def test_launch_uses_isolated_probe_profile_and_exact_sidecar_destination(self) -> None:
        probe = self.launch()

        config = self.create.call_args.args[0]
        self.assertEqual(config.template, SandboxTemplate.SLIM_BASE)
        self.assertTrue(config.agent_egress_probe)
        self.assertTrue(config.vm_runtime)
        self.assertIsNone(config.environment_variables)
        policy = self.sandbox._sandbox._experimental_sidecars.create.call_args.kwargs
        self.assertEqual(policy["outbound_domain_allowlist"], ["run-a.egress.example.com"])
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

    def test_failed_key_generation_cleans_up_sandbox(self) -> None:
        self.sidecar.exec.return_value.returncode = 1

        with self.assertRaises(RuntimeError):
            self.launch()

        self.sandbox.destroy.assert_called_once_with()

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
