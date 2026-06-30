from parameterized import parameterized

from products.engineering_analytics.backend.logic.job_logs.thinning import ThinningConfig, thin_log

_CAP = ThinningConfig().max_lines


class TestThinLog:
    def test_returns_small_log_unchanged(self):
        text = "\n".join(f"step {i}" for i in range(_CAP))
        assert thin_log(text) == text

    def test_keeps_failure_region_warning_and_summary(self):
        noise = [f"downloading package {i}" for i in range(2000)]
        failure = [
            "##[warning]GeoIP database not found, continuing without it",
            "FAILED tests/test_widget.py::test_render - AssertionError: 1 != 2",
            "test result: FAILED. 412 passed; 1 failed",
            "##[error]Process completed with exit code 1.",
        ]
        out = thin_log("\n".join(noise + failure))

        content = [line for line in out.splitlines() if "lines omitted" not in line]
        assert len(content) <= _CAP
        assert "lines omitted" in out
        for line in failure:
            assert line in out
        assert "downloading package 500" not in out

    @parameterized.expand(
        [
            ("errortracking_migration", "Applying posthog.0879_migrate_error_tracking_models... OK"),
            ("zero_failed_summary", "0 failed, 4210 passed"),
            ("error_substring", "set error_code on the row"),
        ]
    )
    def test_substring_noise_is_not_a_marker(self, _name, noise_line):
        middle = [f"{noise_line} #{i}" for i in range(1500)]
        out = thin_log("\n".join([*middle, "##[error]Process completed with exit code 1."]))

        assert f"{noise_line} #700" not in out
        assert "##[error]Process completed with exit code 1." in out

    def test_caps_pathological_log_with_many_markers(self):
        out = thin_log("\n".join(["##[error]boom"] * 5000))

        content = [line for line in out.splitlines() if "lines omitted" not in line]
        assert len(content) <= _CAP
