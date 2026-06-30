from parameterized import parameterized

from products.engineering_analytics.backend.logic.job_logs.thinning import ThinningConfig, thin_log, thin_log_lines

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

    def test_thin_log_lines_anchors_kept_lines_to_original_positions(self):
        # Each kept line keeps its 1-based original position (the only durable anchor once the full
        # log expires); omission markers carry None. A regression here makes a thinned line
        # unlocatable in the real log.
        noise = [f"downloading package {i}" for i in range(2000)]
        lines = thin_log_lines("\n".join([*noise, "##[error]Process completed with exit code 1."]))

        last = lines[-1]
        assert last.text == "##[error]Process completed with exit code 1."
        assert last.original_line_number == 2001  # 2000 noise lines (1..2000), then the failure at 2001
        assert any(line.original_line_number is None and "lines omitted" in line.text for line in lines)

    def test_thin_log_lines_numbers_every_line_when_under_cap(self):
        assert [(line.text, line.original_line_number) for line in thin_log_lines("a\nb\nc")] == [
            ("a", 1),
            ("b", 2),
            ("c", 3),
        ]
