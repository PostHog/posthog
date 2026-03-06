"""Tests for calculate_token_usage tool."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from claude_code_sdk import ResultMessage

from products.review_hog.backend.reviewer.llm.code import (
    _build_claude_code_token_usage,
    _build_codex_token_usage,
    _calculate_codex_cost,
)
from products.review_hog.backend.reviewer.models.calculate_token_usage import (
    AggregatedMetrics,
    BaseUsage,
    MetricsData,
    StepTotals,
    UsageDetails,
)
from products.review_hog.backend.reviewer.tools.calculate_token_usage import TokenUsageCalculator


class TestTokenUsageCalculator:
    """Test TokenUsageCalculator class."""

    def test_init_with_missing_directory(self) -> None:
        """Test initialization with non-existent directory."""
        with pytest.raises(FileNotFoundError, match="Review directory not found"):
            TokenUsageCalculator(Path("/non/existent/path"))

    def test_read_json_missing_file(self, tmp_path: Path) -> None:
        """Test reading a non-existent JSON file."""
        calculator = TokenUsageCalculator(tmp_path)

        with pytest.raises(FileNotFoundError, match="Required file not found"):
            calculator.read_json(tmp_path / "missing.json")

    def test_read_json_valid_file(self, tmp_path: Path) -> None:
        """Test reading a valid JSON file."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create test JSON file
        test_data = {"key": "value", "number": 42}
        test_file = tmp_path / "test.json"
        test_file.write_text(json.dumps(test_data))

        result = calculator.read_json(test_file)
        assert result == test_data

    def test_get_pr_name(self, tmp_path: Path) -> None:
        """Test getting PR name from metadata."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create pr_meta.json
        pr_meta = {"number": 12345, "title": "feat: Add new feature"}
        (tmp_path / "pr_meta.json").write_text(json.dumps(pr_meta))

        result = calculator.get_pr_name()
        assert result == "feat: Add new feature (12345)"

    def test_get_chunking_metrics(self, tmp_path: Path) -> None:
        """Test getting chunking metrics."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create chunks_metrics.json
        metrics_data = {
            "cost_usd": 0.123,
            "duration_ms": 5000,
            "num_turns": 3,
            "session_id": "test-session",
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 300,
                "output_tokens": 400,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (tmp_path / "chunks_metrics.json").write_text(json.dumps(metrics_data))

        result = calculator.get_chunking_metrics()
        assert isinstance(result, MetricsData)
        assert result.cost_usd == 0.123
        assert result.duration_ms == 5000
        assert result.usage.input_tokens == 100

    def test_get_analysis_chunks(self, tmp_path: Path) -> None:
        """Test getting analysis chunks metrics."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create chunk analysis metrics files
        for i in range(1, 3):
            metrics_data = {
                "cost_usd": 0.1 * i,
                "duration_ms": 1000 * i,
                "num_turns": i,
                "session_id": f"session-{i}",
                "usage": {
                    "input_tokens": 10 * i,
                    "cache_creation_input_tokens": 20 * i,
                    "cache_read_input_tokens": 30 * i,
                    "output_tokens": 40 * i,
                    "server_tool_use": {"web_search_requests": 0},
                    "service_tier": "standard",
                },
            }
            (tmp_path / f"chunk-{i}-analysis_metrics.json").write_text(json.dumps(metrics_data))

        result = calculator.get_analysis_chunks()
        assert len(result) == 2
        assert result[0].name == "Chunk 1"
        assert result[0].usage.cost_usd == 0.1
        assert result[1].name == "Chunk 2"
        assert result[1].usage.cost_usd == 0.2

    def test_get_analysis_chunks_no_files(self, tmp_path: Path) -> None:
        """Test getting analysis chunks when no metrics files exist."""
        calculator = TokenUsageCalculator(tmp_path)

        with pytest.raises(FileNotFoundError, match="No chunk analysis metrics files found"):
            calculator.get_analysis_chunks()

    def test_get_pass_chunks(self, tmp_path: Path) -> None:
        """Test getting pass chunks metrics."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create pass directory and chunk files
        pass_dir = tmp_path / "pass1_results"
        pass_dir.mkdir()

        metrics_data = {
            "cost_usd": 0.5,
            "duration_ms": 2000,
            "num_turns": 5,
            "session_id": "pass-session",
            "usage": {
                "input_tokens": 50,
                "cache_creation_input_tokens": 60,
                "cache_read_input_tokens": 70,
                "output_tokens": 80,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (pass_dir / "chunk-1-issues-review_metrics.json").write_text(json.dumps(metrics_data))

        result = calculator.get_pass_chunks(1)
        assert len(result) == 1
        assert result[0].name == "Chunk 1"
        assert result[0].usage.cost_usd == 0.5

    def test_get_deduplication_metrics(self, tmp_path: Path) -> None:
        """Test getting deduplication metrics."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create deduplicator_metrics.json
        metrics_data = {
            "cost_usd": 0.05,
            "duration_ms": 1500,
            "num_turns": 2,
            "session_id": "dedup-session",
            "usage": {
                "input_tokens": 25,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 35,
                "output_tokens": 40,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (tmp_path / "deduplicator_metrics.json").write_text(json.dumps(metrics_data))

        result = calculator.get_deduplication_metrics()
        assert isinstance(result, MetricsData)
        assert result.cost_usd == 0.05
        assert result.usage.input_tokens == 25

    def test_get_pass_validation(self, tmp_path: Path) -> None:
        """Test getting validation metrics for a pass."""
        calculator = TokenUsageCalculator(tmp_path)

        # Create validation directory structure
        val_dir = tmp_path / "pass1_results" / "validation" / "summaries"
        val_dir.mkdir(parents=True)

        # Create validation metrics files
        for i in range(1, 3):
            metrics_data = {
                "cost_usd": 0.03 * i,
                "duration_ms": 500 * i,
                "num_turns": i,
                "session_id": f"val-session-{i}",
                "usage": {
                    "input_tokens": 5 * i,
                    "cache_creation_input_tokens": 10 * i,
                    "cache_read_input_tokens": 15 * i,
                    "output_tokens": 20 * i,
                    "server_tool_use": {"web_search_requests": 0},
                    "service_tier": "standard",
                },
            }
            (val_dir / f"chunk-1-issue-{i}-validation-summary_metrics.json").write_text(json.dumps(metrics_data))

        result = calculator.get_pass_validation(1)
        assert result is not None
        assert result.name == "Pass 1"
        assert len(result.issues) == 2
        assert result.issues[0].issue_id == "issue-1"
        assert result.issues[0].chunk_id == "chunk-1"
        assert result.issues[0].usage.cost_usd == 0.03

    def test_aggregate_metrics_data(self, tmp_path: Path) -> None:
        """Test aggregating metrics data."""
        calculator = TokenUsageCalculator(tmp_path)

        metrics_data = MetricsData(
            cost_usd=0.5,
            duration_ms=1000,
            num_turns=5,
            session_id="test",
            usage=UsageDetails(
                input_tokens=10,
                cache_creation_input_tokens=20,
                cache_read_input_tokens=30,
                output_tokens=40,
            ),
        )

        result = calculator.aggregate_metrics_data(metrics_data)
        assert isinstance(result, AggregatedMetrics)
        assert result.cost_usd == 0.5
        assert result.duration_ms == 1000
        assert result.num_turns == 5
        assert result.usage.input_tokens == 10
        assert result.usage.cache_creation_input_tokens == 20
        assert result.usage.cache_read_input_tokens == 30
        assert result.usage.output_tokens == 40

    def test_sum_aggregated_metrics(self, tmp_path: Path) -> None:
        """Test summing aggregated metrics."""
        calculator = TokenUsageCalculator(tmp_path)

        metrics1 = AggregatedMetrics(
            cost_usd=0.1,
            duration_ms=100,
            num_turns=1,
            usage=BaseUsage(
                input_tokens=10,
                cache_creation_input_tokens=20,
                cache_read_input_tokens=30,
                output_tokens=40,
            ),
        )

        metrics2 = AggregatedMetrics(
            cost_usd=0.2,
            duration_ms=200,
            num_turns=2,
            usage=BaseUsage(
                input_tokens=5,
                cache_creation_input_tokens=10,
                cache_read_input_tokens=15,
                output_tokens=20,
            ),
        )

        result = calculator.sum_aggregated_metrics([metrics1, metrics2])
        assert result.cost_usd == pytest.approx(0.3, rel=1e-9)
        assert result.duration_ms == 300
        assert result.num_turns == 3
        assert result.usage.input_tokens == 15
        assert result.usage.cache_creation_input_tokens == 30
        assert result.usage.cache_read_input_tokens == 45
        assert result.usage.output_tokens == 60


class TestTokenUsageReportE2E:
    """End-to-end test for token usage report generation."""

    def test_complete_token_usage_calculation(self, tmp_path: Path) -> None:
        """Test complete token usage calculation workflow."""
        # Setup test directory structure
        review_dir = tmp_path / "test_review"
        review_dir.mkdir()

        # Create pr_meta.json
        pr_meta = {"number": 999, "title": "test: E2E test PR"}
        (review_dir / "pr_meta.json").write_text(json.dumps(pr_meta))

        # Create chunks_metrics.json
        chunking_metrics = {
            "cost_usd": 0.1,
            "duration_ms": 1000,
            "num_turns": 1,
            "session_id": "chunk-session",
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30,
                "output_tokens": 40,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (review_dir / "chunks_metrics.json").write_text(json.dumps(chunking_metrics))

        # Create chunk analysis metrics
        chunk_analysis_metrics = {
            "cost_usd": 0.2,
            "duration_ms": 2000,
            "num_turns": 2,
            "session_id": "analysis-session",
            "usage": {
                "input_tokens": 20,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 40,
                "output_tokens": 50,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (review_dir / "chunk-1-analysis_metrics.json").write_text(json.dumps(chunk_analysis_metrics))

        # Create pass1_results directory with chunk metrics
        pass1_dir = review_dir / "pass1_results"
        pass1_dir.mkdir()

        pass_chunk_metrics = {
            "cost_usd": 0.3,
            "duration_ms": 3000,
            "num_turns": 3,
            "session_id": "pass-session",
            "usage": {
                "input_tokens": 30,
                "cache_creation_input_tokens": 40,
                "cache_read_input_tokens": 50,
                "output_tokens": 60,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (pass1_dir / "chunk-1-issues-review_metrics.json").write_text(json.dumps(pass_chunk_metrics))

        # Create deduplication metrics
        dedup_metrics = {
            "cost_usd": 0.05,
            "duration_ms": 500,
            "num_turns": 1,
            "session_id": "dedup-session",
            "usage": {
                "input_tokens": 5,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 15,
                "output_tokens": 20,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (review_dir / "deduplicator_metrics.json").write_text(json.dumps(dedup_metrics))

        # Create validation metrics
        val_dir = pass1_dir / "validation" / "summaries"
        val_dir.mkdir(parents=True)

        validation_metrics = {
            "cost_usd": 0.04,
            "duration_ms": 400,
            "num_turns": 1,
            "session_id": "val-session",
            "usage": {
                "input_tokens": 4,
                "cache_creation_input_tokens": 8,
                "cache_read_input_tokens": 12,
                "output_tokens": 16,
                "server_tool_use": {"web_search_requests": 0},
                "service_tier": "standard",
            },
        }
        (val_dir / "chunk-1-issue-1-validation-summary_metrics.json").write_text(json.dumps(validation_metrics))

        # Run the calculator
        calculator = TokenUsageCalculator(review_dir)
        report = calculator.calculate()

        # Verify report structure
        assert report.name == "test: E2E test PR (999)"

        # Verify chunking metrics
        assert report.chunking.cost_usd == 0.1
        assert report.chunking.usage.input_tokens == 10

        # Verify analysis metrics
        assert "chunks" in report.analysis
        assert len(report.analysis["chunks"]) == 1
        assert report.analysis["chunks"][0].name == "Chunk 1"
        assert report.analysis["chunks"][0].usage.cost_usd == 0.2

        # Verify issue search metrics
        assert len(report.issues_search) == 1
        assert report.issues_search[0].name == "Pass 1"
        assert len(report.issues_search[0].chunks) == 1
        assert report.issues_search[0].chunks[0].usage.cost_usd == 0.3

        # Verify deduplication metrics
        assert report.deduplication.cost_usd == 0.05
        assert report.deduplication.usage.input_tokens == 5

        # Verify validation metrics
        assert len(report.validation) == 1
        assert report.validation[0].name == "Pass 1"
        assert len(report.validation[0].issues) == 1
        assert report.validation[0].issues[0].issue_id == "issue-1"
        assert report.validation[0].issues[0].usage.cost_usd == 0.04

        # Verify step totals
        assert report.step_totals is not None
        assert isinstance(report.step_totals, StepTotals)
        assert report.step_totals.chunking.cost_usd == 0.1
        assert report.step_totals.chunking.usage.input_tokens == 10
        assert report.step_totals.analysis.cost_usd == 0.2
        assert report.step_totals.analysis.usage.input_tokens == 20
        assert report.step_totals.issues_search.cost_usd == 0.3
        assert report.step_totals.issues_search.usage.input_tokens == 30
        assert report.step_totals.deduplication.cost_usd == 0.05
        assert report.step_totals.deduplication.usage.input_tokens == 5
        assert report.step_totals.validation.cost_usd == 0.04
        assert report.step_totals.validation.usage.input_tokens == 4

        # Verify grand total
        assert report.total is not None
        assert isinstance(report.total, AggregatedMetrics)
        assert report.total.cost_usd == pytest.approx(0.69, rel=1e-9)
        assert report.total.usage.input_tokens == 69
        assert report.total.usage.cache_creation_input_tokens == 108
        assert report.total.usage.cache_read_input_tokens == 147
        assert report.total.usage.output_tokens == 186

        # Save and verify output file
        output_path = review_dir / "total_token_count_metrics.json"
        calculator.save_report(report, output_path)

        assert output_path.exists()

        # Load and verify saved data
        with output_path.open() as f:
            saved_data = json.load(f)

        assert saved_data["name"] == "test: E2E test PR (999)"
        assert saved_data["chunking"]["cost_usd"] == 0.1
        assert saved_data["deduplication"]["cost_usd"] == 0.05
        assert len(saved_data["validation"]) == 1

        # Verify step_totals in saved data
        assert "step_totals" in saved_data
        assert saved_data["step_totals"]["chunking"]["cost_usd"] == 0.1
        assert saved_data["step_totals"]["analysis"]["cost_usd"] == 0.2
        assert saved_data["step_totals"]["issues_search"]["cost_usd"] == 0.3
        assert saved_data["step_totals"]["deduplication"]["cost_usd"] == 0.05
        assert saved_data["step_totals"]["validation"]["cost_usd"] == 0.04

        # Verify total in saved data
        assert "total" in saved_data
        assert saved_data["total"]["cost_usd"] == pytest.approx(0.69, rel=1e-9)
        assert saved_data["total"]["usage"]["input_tokens"] == 69


class TestCodexTokenUsage:
    """Test Codex token usage calculation."""

    def test_codex_helper_functions(self) -> None:
        """Test the Codex helper functions for token calculation."""
        # Test data
        token_count_data = {
            "input_tokens": 9504,
            "cached_input_tokens": 5120,
            "output_tokens": 2266,
            "reasoning_output_tokens": 1664,
        }

        # Test calculate_codex_cost
        cost = _calculate_codex_cost(token_count_data)
        assert cost == pytest.approx(0.02878, rel=1e-6)

        # Test build_codex_token_usage
        usage = _build_codex_token_usage(token_count_data, cost)
        assert usage.cost_usd == pytest.approx(0.02878, rel=1e-6)
        assert usage.duration_ms == 0
        assert usage.num_turns == 0
        assert usage.session_id == ""  # Empty string instead of None
        assert usage.usage.input_tokens == 9504
        assert usage.usage.cache_creation_input_tokens == 5120
        assert usage.usage.cache_read_input_tokens == 0
        assert usage.usage.output_tokens == 2266
        assert usage.usage.reasoning_output_tokens == 1664

    def test_codex_edge_cases(self) -> None:
        """Test edge cases for Codex token calculation."""

        # Test with zero tokens
        zero_data = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
        }
        cost = _calculate_codex_cost(zero_data)
        assert cost == 0.0
        usage = _build_codex_token_usage(zero_data, cost)
        assert usage.cost_usd == 0.0

        # Test with missing keys (should use defaults)
        partial_data = {"input_tokens": 1000}
        cost = _calculate_codex_cost(partial_data)
        assert cost == pytest.approx(0.00125, rel=1e-6)  # Only input cost

        # Test that reasoning tokens don't affect cost
        with_reasoning = {
            "input_tokens": 1000,
            "cached_input_tokens": 0,
            "output_tokens": 1000,
            "reasoning_output_tokens": 10000,  # Large number that should be ignored
        }
        without_reasoning = {
            "input_tokens": 1000,
            "cached_input_tokens": 0,
            "output_tokens": 1000,
            "reasoning_output_tokens": 0,
        }
        cost_with = _calculate_codex_cost(with_reasoning)
        cost_without = _calculate_codex_cost(without_reasoning)
        assert cost_with == cost_without  # Reasoning tokens should not affect cost


class TestClaudeCodeTokenUsage:
    """Test Claude Code token usage calculation."""

    def test_claude_code_helper_function(self) -> None:
        """Test the Claude Code helper function for building token usage."""
        # Create a mock ResultMessage
        mock_message = Mock(spec=ResultMessage)
        mock_message.total_cost_usd = 0.05432
        mock_message.duration_ms = 3500
        mock_message.num_turns = 7
        mock_message.session_id = "test-session-123"
        mock_message.usage = {
            "input_tokens": 1500,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 200,
            "output_tokens": 800,
        }

        # Test build_claude_code_token_usage
        usage = _build_claude_code_token_usage(mock_message)

        assert usage.cost_usd == 0.05432
        assert usage.duration_ms == 3500
        assert usage.num_turns == 7
        assert usage.session_id == "test-session-123"
        assert usage.usage.input_tokens == 1500
        assert usage.usage.cache_creation_input_tokens == 500
        assert usage.usage.cache_read_input_tokens == 200
        assert usage.usage.output_tokens == 800

    def test_claude_code_without_usage(self) -> None:
        """Test Claude Code helper with no usage data."""
        # Create a mock ResultMessage without usage
        mock_message = Mock(spec=ResultMessage)
        mock_message.total_cost_usd = 0.01234
        mock_message.duration_ms = 1200
        mock_message.num_turns = 2
        mock_message.session_id = "no-usage-session"
        mock_message.usage = None

        # Test build_claude_code_token_usage
        usage = _build_claude_code_token_usage(mock_message)

        assert usage.cost_usd == 0.01234
        assert usage.duration_ms == 1200
        assert usage.num_turns == 2
        assert usage.session_id == "no-usage-session"
        # When no usage data is provided, it should use default UsageDetails
        assert usage.usage.input_tokens == 0
        assert usage.usage.output_tokens == 0
