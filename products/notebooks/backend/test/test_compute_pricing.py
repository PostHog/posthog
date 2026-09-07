from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import User

from products.notebooks.backend.compute_pricing import (
    COMPUTE_PRESETS,
    DEFAULT_COMPUTE_PRESET_KEY,
    find_matching_preset,
    get_compute_rates,
    get_default_compute_preset,
)
from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config
from products.notebooks.backend.models import KernelRuntime, Notebook


class TestComputePricing(SimpleTestCase):
    @parameterized.expand(
        [
            ("us_default_sandbox", "US", 1, 2, 0.25),
            ("us_balanced", "US", 4, 8, 1.00),
            ("us_high_memory", "US", 8, 32, 2.40),
            ("us_memory_only_shape", "US", 1, 64, 1.80),
            ("eu_carries_the_uplift", "EU", 4, 8, 1.15),
            ("dev_is_priced_as_us", "DEV", 4, 8, 1.00),
        ]
    )
    def test_hourly_price_sums_the_two_rates(
        self, _name: str, region: str, cpu_cores: float, memory_gb: float, expected: float
    ) -> None:
        rates = get_compute_rates(region)

        assert rates.hourly_price(cpu_cores=cpu_cores, memory_gb=memory_gb) == expected

    @parameterized.expand([("US",), ("EU",)])
    def test_every_preset_is_priced_at_the_region_rates(self, region: str) -> None:
        rates = get_compute_rates(region)

        for preset in COMPUTE_PRESETS:
            expected = round(
                preset.cpu_cores * rates.cpu_per_core_hour + preset.memory_gb * rates.memory_per_gb_hour, 4
            )
            assert rates.hourly_price(cpu_cores=preset.cpu_cores, memory_gb=preset.memory_gb) == expected

    @parameterized.expand(
        [
            ("exact_preset_shape", 4, 8, "balanced"),
            ("tuned_shape_matches_nothing", 6, 8, None),
            ("unset_cpu_matches_nothing", None, 8, None),
        ]
    )
    def test_find_matching_preset(
        self, _name: str, cpu_cores: float | None, memory_gb: float | None, expected_key: str | None
    ) -> None:
        preset = find_matching_preset(cpu_cores=cpu_cores, memory_gb=memory_gb)

        assert (preset.key if preset else None) == expected_key


class TestComputeOptionsEndpoint(APIBaseTest):
    def test_returns_presets_priced_at_the_instance_rates(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/kernel/compute_options/")

        assert response.status_code == 200, response.json()
        payload = response.json()
        rates = get_compute_rates()
        assert payload["cpu_rate_per_core_hour"] == rates.cpu_per_core_hour
        assert payload["default_preset_key"] == DEFAULT_COMPUTE_PRESET_KEY
        assert [preset["key"] for preset in payload["presets"]] == [preset.key for preset in COMPUTE_PRESETS]
        for quoted, preset in zip(payload["presets"], COMPUTE_PRESETS):
            assert quoted["hourly_price"] == rates.hourly_price(cpu_cores=preset.cpu_cores, memory_gb=preset.memory_gb)

    def test_offered_preset_shapes_are_all_configurable(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/kernel/compute_options/")

        payload = response.json()
        for preset in payload["presets"]:
            assert preset["cpu_cores"] in payload["allowed_cpu_cores"]
            assert preset["memory_gb"] in payload["allowed_memory_gb"]

    def test_status_quotes_the_shape_the_notebook_will_get(self) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=4, kernel_memory_gb=8)

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/status/",
        )

        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["hourly_price"] == get_compute_rates().hourly_price(cpu_cores=4, memory_gb=8)
        assert payload["preset_key"] == "balanced"

    def test_config_quotes_the_default_for_knobs_the_notebook_leaves_unset(self) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        default_preset = get_default_compute_preset()

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"idle_timeout_seconds": 1800},
        )

        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["cpu_cores"] is None
        assert payload["hourly_price"] == get_compute_rates().hourly_price(
            cpu_cores=default_preset.cpu_cores, memory_gb=default_preset.memory_gb
        )
        assert payload["preset_key"] == DEFAULT_COMPUTE_PRESET_KEY

    def _live_kernel(self, notebook: Notebook) -> KernelRuntime:
        return KernelRuntime.objects.create(
            team=self.team,
            notebook=notebook,
            notebook_short_id=notebook.short_id,
            user=self.user,
            status=KernelRuntime.Status.RUNNING,
            backend=KernelRuntime.Backend.MODAL,
            provisioned_cpu_cores=notebook.kernel_cpu_cores,
            provisioned_memory_gb=notebook.kernel_memory_gb,
        )

    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=True,
    )
    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_a_resize_restarts_the_live_kernel(self, mock_runtime: MagicMock, _alive: MagicMock) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        self._live_kernel(notebook)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 4, "memory_gb": 8},
        )

        assert response.status_code == 200, response.json()
        mock_runtime.return_value.restart.assert_called_once()
        payload = response.json()
        assert payload["restarted"] is True
        # The quote now describes the sandbox that is actually running.
        assert payload["restart_required"] is False

    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=True,
    )
    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_an_idle_timeout_change_leaves_the_kernel_alone(self, mock_runtime: MagicMock, _alive: MagicMock) -> None:
        # A restart discards every materialized dataframe, which is far too much to spend on a
        # setting a live sandbox cannot pick up anyway.
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=4, kernel_memory_gb=8)
        self._live_kernel(notebook)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"idle_timeout_seconds": 1800},
        )

        assert response.status_code == 200, response.json()
        mock_runtime.return_value.restart.assert_not_called()
        payload = response.json()
        assert payload["restarted"] is False
        assert payload["restart_required"] is True

    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_a_resize_with_no_live_kernel_starts_nothing(self, mock_runtime: MagicMock) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 4, "memory_gb": 8},
        )

        assert response.status_code == 200, response.json()
        mock_runtime.return_value.restart.assert_not_called()
        assert response.json()["restarted"] is False

    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=True,
    )
    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_a_collaborators_kernel_is_not_restarted(self, mock_runtime: MagicMock, _alive: MagicMock) -> None:
        # Runtimes are per user. Restarting on someone else's row would provision a paid sandbox
        # for the caller and leave the collaborator on the old shape.
        other = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        runtime = self._live_kernel(notebook)
        runtime.user = other
        runtime.save(update_fields=["user"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 4, "memory_gb": 8},
        )

        assert response.status_code == 200, response.json()
        mock_runtime.return_value.restart.assert_not_called()
        assert response.json()["restarted"] is False

    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=False,
    )
    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_a_stale_running_row_does_not_provision_compute(self, mock_runtime: MagicMock, _alive: MagicMock) -> None:
        # A RUNNING row can outlive its sandbox. Acting on it would turn a config-only call into
        # new paid compute.
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        self._live_kernel(notebook)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 4, "memory_gb": 8},
        )

        assert response.status_code == 200, response.json()
        mock_runtime.return_value.restart.assert_not_called()
        assert response.json()["restarted"] is False

    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=True,
    )
    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_a_failed_restart_keeps_the_shape_that_is_running(self, mock_runtime: MagicMock, _alive: MagicMock) -> None:
        # The write has to precede the restart because the restart reads it. When the restart does
        # not happen, the old sandbox is still running, so the row has to go back or every later
        # status prices a shape nobody is on.
        mock_runtime.return_value.restart.side_effect = RuntimeError("lock timeout")
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        self._live_kernel(notebook)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 8, "memory_gb": 16},
        )

        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["restarted"] is False
        assert payload["restart_required"] is True
        # This response prices the same thing status does: the sandbox still serving the notebook,
        # not the size that failed to apply.
        assert payload["hourly_price"] == get_compute_rates().hourly_price(cpu_cores=1, memory_gb=2)

        # The requested size is kept: it is what the next sandbox gets.
        notebook.refresh_from_db()
        assert notebook.kernel_cpu_cores == 8
        assert notebook.kernel_memory_gb == 16

        # But status prices the sandbox that is actually running, which is where the old bug
        # became permanent — every poll quoted the shape that failed to apply.
        status_payload = self.client.get(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/status/"
        ).json()
        assert status_payload["hourly_price"] == get_compute_rates().hourly_price(cpu_cores=1, memory_gb=2)

    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=True,
    )
    @patch("products.notebooks.backend.presentation.views.notebook.get_kernel_runtime")
    def test_a_failed_resize_retries_on_an_identical_second_request(
        self, mock_runtime: MagicMock, _alive: MagicMock
    ) -> None:
        # A transient restart failure leaves the sandbox on the old shape. Re-sending the same size
        # has to attempt the restart again, or the resize is wedged until the sandbox idles out.
        mock_runtime.return_value.restart.side_effect = [RuntimeError("lock timeout"), None]
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        self._live_kernel(notebook)

        first = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 8, "memory_gb": 16},
        )
        assert first.status_code == 200, first.json()
        assert first.json()["restarted"] is False

        second = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/config/",
            {"cpu_cores": 8, "memory_gb": 16},
        )
        assert second.status_code == 200, second.json()
        assert second.json()["restarted"] is True
        assert mock_runtime.return_value.restart.call_count == 2

    def test_status_prices_the_running_sandbox_not_the_configuration(self) -> None:
        # The notebook is configured for a bigger shape than the live sandbox was built with,
        # which is the state a resize leaves until a restart applies it.
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        runtime = self._live_kernel(notebook)
        notebook.kernel_cpu_cores = 8
        notebook.kernel_memory_gb = 16
        notebook.save(update_fields=["kernel_cpu_cores", "kernel_memory_gb"])

        payload = self.client.get(f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/status/").json()

        assert runtime.provisioned_cpu_cores == 1
        assert payload["hourly_price"] == get_compute_rates().hourly_price(cpu_cores=1, memory_gb=2)
        assert payload["preset_key"] == "small"

    def test_status_prices_the_configuration_when_nothing_is_running(self) -> None:
        # With no live sandbox the configured shape is what the next one costs, so quote that.
        notebook = Notebook.objects.create(
            team=self.team, created_by=self.user, kernel_cpu_cores=8, kernel_memory_gb=16
        )

        payload = self.client.get(f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/kernel/status/").json()

        assert payload["hourly_price"] == get_compute_rates().hourly_price(cpu_cores=8, memory_gb=16)

    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    @patch(
        "products.notebooks.backend.presentation.views.notebook.NotebookViewSet._sandbox_is_running",
        return_value=True,
    )
    def test_a_run_reusing_a_live_sandbox_discloses_nothing(
        self, _flag: MagicMock, _alive: MagicMock, _workflow: MagicMock
    ) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)
        self._live_kernel(notebook)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/sql_v2/run/",
            {"node_id": "n1", "code": "print(1)", "node_type": "python"},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["starts_sandbox"] is False

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    @patch("products.notebooks.backend.presentation.views.notebook.start_sql_v2_run_workflow")
    def test_a_run_with_no_live_sandbox_discloses_the_start(self, _flag: MagicMock, _workflow: MagicMock) -> None:
        # The client used to answer this from a kernel poll up to ten seconds old, which stayed
        # silent through a sandbox that timed out between polls.
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, kernel_cpu_cores=1, kernel_memory_gb=2)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/sql_v2/run/",
            {"node_id": "n1", "code": "print(1)", "node_type": "python"},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["starts_sandbox"] is True

    @patch("products.notebooks.backend.presentation.views.notebook.is_sql_v2_enabled", return_value=True)
    @patch("products.notebooks.backend.presentation.views.notebook.enqueue_direct_run")
    def test_a_pure_hogql_run_never_discloses_a_sandbox(self, _flag: MagicMock, _direct: MagicMock) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks/{notebook.short_id}/sql_v2/run/",
            {"node_id": "n1", "code": "select 1", "node_type": "hogql"},
        )

        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["starts_sandbox"] is False
        assert payload["sandbox_hourly_price"] is None

    def test_a_new_sandbox_gets_the_default_preset_shape(self) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        default_preset = get_default_compute_preset()

        sandbox_config = build_notebook_sandbox_config(notebook)

        assert sandbox_config.cpu_cores == default_preset.cpu_cores
        assert sandbox_config.memory_gb == default_preset.memory_gb
