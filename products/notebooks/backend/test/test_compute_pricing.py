from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.notebooks.backend.compute_pricing import (
    COMPUTE_PRESETS,
    DEFAULT_COMPUTE_PRESET_KEY,
    find_matching_preset,
    get_compute_rates,
    get_default_compute_preset,
)
from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config
from products.notebooks.backend.models import Notebook


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
        assert payload["next_hourly_price"] == get_compute_rates().hourly_price(cpu_cores=4, memory_gb=8)
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
        assert payload["next_hourly_price"] == get_compute_rates().hourly_price(
            cpu_cores=default_preset.cpu_cores, memory_gb=default_preset.memory_gb
        )
        assert payload["preset_key"] == DEFAULT_COMPUTE_PRESET_KEY

    def test_a_new_sandbox_gets_the_default_preset_shape(self) -> None:
        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        default_preset = get_default_compute_preset()

        sandbox_config = build_notebook_sandbox_config(notebook)

        assert sandbox_config.cpu_cores == default_preset.cpu_cores
        assert sandbox_config.memory_gb == default_preset.memory_gb
