import pytest

from products.llm_analytics.backend.text_repr.formatters.constants import PRESERVE_HEADER_LINES
from products.llm_analytics.backend.text_repr.formatters.message_formatter import reduce_by_uniform_sampling


def _create_numbered_text(num_lines: int, line_content_length: int = 50) -> str:
    lines = []
    padding = len(str(num_lines))
    for i in range(1, num_lines + 1):
        line_num = str(i).zfill(padding)
        content = "x" * line_content_length
        lines.append(f"L{line_num}: {content}")
    return "\n".join(lines)


class TestReduceByUniformSampling:
    def test_text_under_max_length_unchanged(self):
        text = _create_numbered_text(10, line_content_length=20)
        result, was_sampled = reduce_by_uniform_sampling(text, max_length=10000)
        assert result == text
        assert was_sampled is False

    def test_text_exactly_at_max_length_unchanged(self):
        text = _create_numbered_text(10, line_content_length=20)
        result, was_sampled = reduce_by_uniform_sampling(text, max_length=len(text))
        assert result == text
        assert was_sampled is False

    def test_large_text_is_sampled(self):
        text = _create_numbered_text(1000, line_content_length=100)
        max_length = 5000
        result, was_sampled = reduce_by_uniform_sampling(text, max_length=max_length)
        assert len(result) <= max_length
        assert was_sampled is True

    def test_sampled_text_contains_header_note(self):
        text = _create_numbered_text(1000, line_content_length=100)
        result, was_sampled = reduce_by_uniform_sampling(text, max_length=5000)
        assert "[SAMPLED VIEW:" in result
        assert "Gaps in line numbers indicate omitted content" in result
        assert was_sampled is True

    def test_header_lines_are_preserved(self):
        lines = [f"L{str(i).zfill(3)}: Header {i}" for i in range(1, PRESERVE_HEADER_LINES + 1)]
        for i in range(PRESERVE_HEADER_LINES + 1, 1001):
            lines.append(f"L{str(i).zfill(4)}: Body line {i}")
        text = "\n".join(lines)

        result, _ = reduce_by_uniform_sampling(text, max_length=3000)

        for i in range(1, PRESERVE_HEADER_LINES + 1):
            assert f"Header {i}" in result

    def test_sampled_lines_show_gaps_in_line_numbers(self):
        text = _create_numbered_text(100, line_content_length=100)
        result, _ = reduce_by_uniform_sampling(text, max_length=2000)
        result_lines = result.split("\n")

        line_numbers = []
        for line in result_lines:
            if line.startswith("L") and ": " in line[:15]:
                num_part = line[1 : line.index(": ")]
                if num_part.isdigit():
                    line_numbers.append(int(num_part))

        if len(line_numbers) > 1:
            gaps = [line_numbers[i + 1] - line_numbers[i] for i in range(len(line_numbers) - 1)]
            has_gap = any(gap > 1 for gap in gaps)
            assert has_gap

    def test_sample_header_inserted_after_first_two_lines(self):
        text = _create_numbered_text(1000, line_content_length=100)
        result, _ = reduce_by_uniform_sampling(text, max_length=5000)
        result_lines = result.split("\n")

        assert result_lines[0].startswith("L")
        assert result_lines[1].startswith("L")
        assert "[SAMPLED VIEW:" in result_lines[2]

    @pytest.mark.parametrize(
        "num_lines,max_length",
        [
            (100, 2000),
            (500, 5000),
            (1000, 10000),
            (5000, 50000),
        ],
    )
    def test_result_fits_within_max_length(self, num_lines: int, max_length: int):
        text = _create_numbered_text(num_lines, line_content_length=100)
        result, _ = reduce_by_uniform_sampling(text, max_length=max_length)
        assert len(result) <= max_length

    def test_very_small_max_length_reduces_aggressively(self):
        text = _create_numbered_text(100, line_content_length=50)
        result, _ = reduce_by_uniform_sampling(text, max_length=1000)
        assert len(result) <= 1000

    def test_text_with_only_header_lines_unchanged(self):
        text = _create_numbered_text(PRESERVE_HEADER_LINES, line_content_length=20)
        result, was_sampled = reduce_by_uniform_sampling(text, max_length=100)
        assert result == text
        assert was_sampled is False

    def test_empty_text_unchanged(self):
        result, was_sampled = reduce_by_uniform_sampling("", max_length=1000)
        assert result == ""
        assert was_sampled is False

    def test_percentage_in_header_is_accurate(self):
        text = _create_numbered_text(1000, line_content_length=100)
        result, _ = reduce_by_uniform_sampling(text, max_length=10000)

        import re

        match = re.search(r"Showing ~(\d+)% of ([\d,]+) lines", result)
        assert match is not None

        reported_percent = int(match.group(1))
        total_lines = int(match.group(2).replace(",", ""))

        assert total_lines == 1000

        body_lines_in_result = sum(
            1 for line in result.split("\n") if line.startswith("L") and "[SAMPLED VIEW:" not in line
        )
        actual_percent = (body_lines_in_result / total_lines) * 100

        assert abs(reported_percent - actual_percent) < 5
