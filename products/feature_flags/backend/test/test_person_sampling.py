from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.person_sampling import bounded_memory_settings, count_settings


class TestPersonSamplingSettings(SimpleTestCase):
    @parameterized.expand(
        [
            ("memory bounded", bounded_memory_settings),
            ("sampled count", lambda: count_settings(64)),
            ("exact count", lambda: count_settings(None)),
        ]
    )
    def test_settings_reject_a_partial_result_on_timeout(self, _name, build_settings):
        # Left unset, the mode inherits the cluster profile, which may return whatever the
        # query aggregated before the timeout. The sampled count would then multiply that
        # partial tally by the modulus and report it as an audience size.
        assert build_settings().timeout_overflow_mode == "throw"
