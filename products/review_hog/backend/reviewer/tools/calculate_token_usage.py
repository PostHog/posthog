import json
import logging
import re
from pathlib import Path

from products.review_hog.backend.reviewer.models.calculate_token_usage import (
    AggregatedMetrics,
    BaseUsage,
    ChunkMetrics,
    MetricsData,
    PassChunks,
    PassValidation,
    StepTotals,
    TokenUsageReport,
    ValidationIssue,
)

# Set up logging
logger = logging.getLogger(__name__)


class TokenUsageCalculator:
    """Calculator for token usage metrics across PR review process."""

    def __init__(self, review_dir: Path):
        """Initialize calculator with review directory path."""
        self.review_dir = Path(review_dir)
        if not self.review_dir.exists():
            raise FileNotFoundError(f"Review directory not found: {review_dir}")

    def read_json(self, file_path: Path) -> dict:
        """Read JSON file and return parsed content."""
        if not file_path.exists():
            raise FileNotFoundError(f"Required file not found: {file_path}")
        with file_path.open() as f:
            return json.load(f)

    def get_pr_name(self) -> str:
        """Get PR name from metadata."""
        pr_meta = self.read_json(self.review_dir / "pr_meta.json")
        number = pr_meta.get("number", "")
        title = pr_meta.get("title", "")
        return f"{title} ({number})"

    def get_chunking_metrics(self) -> MetricsData:
        """Get chunking step metrics."""
        metrics_file = self.review_dir / "chunks_metrics.json"
        data = self.read_json(metrics_file)
        return MetricsData(**data)

    def get_analysis_chunks(self) -> list[ChunkMetrics]:
        """Get analysis metrics for all chunks."""
        chunks = []

        # Find all chunk analysis files
        chunk_files = sorted(self.review_dir.glob("chunk-*-analysis_metrics.json"))

        if not chunk_files:
            raise FileNotFoundError("No chunk analysis metrics files found")

        for chunk_file in chunk_files:
            # Extract chunk number from filename
            match = re.match(r"chunk-(\d+)-analysis_metrics\.json", chunk_file.name)
            if match:
                chunk_num = match.group(1)
                data = self.read_json(chunk_file)
                chunks.append(
                    ChunkMetrics(name=f"Chunk {chunk_num}", usage=MetricsData(**data))
                )

        return chunks

    def get_pass_chunks(self, pass_num: int) -> list[ChunkMetrics]:
        """Get issue search metrics for all chunks in a pass."""
        chunks: list[ChunkMetrics] = []
        pass_dir = self.review_dir / f"pass{pass_num}_results"

        if not pass_dir.exists():
            return chunks

        # Find all chunk issue review files
        chunk_files = sorted(pass_dir.glob("chunk-*-issues-review_metrics.json"))

        for chunk_file in chunk_files:
            # Extract chunk number from filename
            match = re.match(
                r"chunk-(\d+)-issues-review_metrics\.json", chunk_file.name
            )
            if match:
                chunk_num = match.group(1)
                data = self.read_json(chunk_file)
                chunks.append(
                    ChunkMetrics(name=f"Chunk {chunk_num}", usage=MetricsData(**data))
                )

        return chunks

    def get_all_passes(self) -> list[PassChunks]:
        """Get issue search metrics for all passes."""
        passes = []
        pass_num = 1

        while True:
            pass_dir = self.review_dir / f"pass{pass_num}_results"
            if not pass_dir.exists():
                break

            chunks = self.get_pass_chunks(pass_num)
            if chunks:
                passes.append(PassChunks(name=f"Pass {pass_num}", chunks=chunks))

            pass_num += 1

        if not passes:
            raise FileNotFoundError("No pass results directories found")

        return passes

    def get_deduplication_metrics(self) -> MetricsData:
        """Get deduplication step metrics."""
        metrics_file = self.review_dir / "deduplicator_metrics.json"
        if not metrics_file.exists():
            raise FileNotFoundError(
                f"Deduplication metrics file not found: {metrics_file}"
            )
        data = self.read_json(metrics_file)
        return MetricsData(**data)

    def get_pass_validation(self, pass_num: int) -> PassValidation | None:
        """Get validation metrics for a single pass."""
        pass_dir = (
            self.review_dir / f"pass{pass_num}_results" / "validation" / "summaries"
        )

        if not pass_dir.exists():
            return None

        issues = []

        # Find all validation summary metrics files
        validation_files = sorted(
            pass_dir.glob("chunk-*-issue-*-validation-summary_metrics.json")
        )

        for val_file in validation_files:
            # Extract chunk and issue numbers from filename
            match = re.match(
                r"chunk-(\d+)-issue-(\d+)-validation-summary_metrics\.json",
                val_file.name,
            )
            if match:
                chunk_num = match.group(1)
                issue_num = match.group(2)
                data = self.read_json(val_file)
                issues.append(
                    ValidationIssue(
                        issue_id=f"issue-{issue_num}",
                        chunk_id=f"chunk-{chunk_num}",
                        usage=MetricsData(**data),
                    )
                )

        if issues:
            return PassValidation(name=f"Pass {pass_num}", issues=issues)
        return None

    def get_all_validation(self) -> list[PassValidation]:
        """Get validation metrics for all passes."""
        validations = []
        pass_num = 1

        while True:
            pass_dir = self.review_dir / f"pass{pass_num}_results"
            if not pass_dir.exists():
                break

            pass_validation = self.get_pass_validation(pass_num)
            if pass_validation:
                validations.append(pass_validation)

            pass_num += 1

        return validations

    def aggregate_metrics_data(self, metrics: MetricsData) -> AggregatedMetrics:
        """Convert MetricsData to AggregatedMetrics."""
        return AggregatedMetrics(
            cost_usd=metrics.cost_usd,
            duration_ms=metrics.duration_ms,
            num_turns=metrics.num_turns,
            usage=BaseUsage(
                input_tokens=metrics.usage.input_tokens,
                cache_creation_input_tokens=metrics.usage.cache_creation_input_tokens,
                cache_read_input_tokens=metrics.usage.cache_read_input_tokens,
                output_tokens=metrics.usage.output_tokens,
            ),
        )

    def sum_aggregated_metrics(
        self, metrics_list: list[AggregatedMetrics]
    ) -> AggregatedMetrics:
        """Sum a list of aggregated metrics."""
        total = AggregatedMetrics()
        for metrics in metrics_list:
            total.cost_usd += metrics.cost_usd
            total.duration_ms += metrics.duration_ms
            total.num_turns += metrics.num_turns
            total.usage.input_tokens += metrics.usage.input_tokens
            total.usage.cache_creation_input_tokens += (
                metrics.usage.cache_creation_input_tokens
            )
            total.usage.cache_read_input_tokens += metrics.usage.cache_read_input_tokens
            total.usage.output_tokens += metrics.usage.output_tokens
        return total

    def calculate_analysis_total(
        self, analysis_chunks: list[ChunkMetrics]
    ) -> AggregatedMetrics:
        """Calculate total for analysis step."""
        metrics_list = [
            self.aggregate_metrics_data(chunk.usage) for chunk in analysis_chunks
        ]
        return self.sum_aggregated_metrics(metrics_list)

    def calculate_issues_search_total(
        self, issues_search: list[PassChunks]
    ) -> AggregatedMetrics:
        """Calculate total for issues search step."""
        metrics_list = []
        for pass_chunks in issues_search:
            for chunk in pass_chunks.chunks:
                metrics_list.append(self.aggregate_metrics_data(chunk.usage))
        return self.sum_aggregated_metrics(metrics_list)

    def calculate_validation_total(
        self, validation: list[PassValidation]
    ) -> AggregatedMetrics:
        """Calculate total for validation step."""
        metrics_list = []
        for pass_validation in validation:
            for issue in pass_validation.issues:
                metrics_list.append(self.aggregate_metrics_data(issue.usage))
        return self.sum_aggregated_metrics(metrics_list)

    def calculate_step_totals(
        self,
        chunking: MetricsData,
        analysis_chunks: list[ChunkMetrics],
        issues_search: list[PassChunks],
        deduplication: MetricsData,
        validation: list[PassValidation],
    ) -> StepTotals:
        """Calculate totals for each processing step."""
        return StepTotals(
            chunking=self.aggregate_metrics_data(chunking),
            analysis=self.calculate_analysis_total(analysis_chunks),
            issues_search=self.calculate_issues_search_total(issues_search),
            deduplication=self.aggregate_metrics_data(deduplication),
            validation=self.calculate_validation_total(validation),
        )

    def calculate_grand_total(self, step_totals: StepTotals) -> AggregatedMetrics:
        """Calculate grand total from all steps."""
        all_steps = [
            step_totals.chunking,
            step_totals.analysis,
            step_totals.issues_search,
            step_totals.deduplication,
            step_totals.validation,
        ]
        return self.sum_aggregated_metrics(all_steps)

    def calculate(self) -> TokenUsageReport:
        """Calculate complete token usage report."""
        logger.info(f"Processing review directory: {self.review_dir}")

        # Get PR name
        logger.info("Getting PR metadata...")
        name = self.get_pr_name()

        # Get chunking metrics
        logger.info("Getting chunking metrics...")
        chunking = self.get_chunking_metrics()

        # Get analysis metrics
        logger.info("Getting analysis metrics...")
        analysis_chunks = self.get_analysis_chunks()

        # Get issue search metrics for all passes
        logger.info("Getting issue search metrics...")
        issues_search = self.get_all_passes()

        # Get deduplication metrics
        logger.info("Getting deduplication metrics...")
        deduplication = self.get_deduplication_metrics()

        # Get validation metrics
        logger.info("Getting validation metrics...")
        validation = self.get_all_validation()

        # Calculate step totals
        logger.info("Calculating step totals...")
        step_totals = self.calculate_step_totals(
            chunking, analysis_chunks, issues_search, deduplication, validation
        )

        # Calculate grand total
        logger.info("Calculating grand total...")
        grand_total = self.calculate_grand_total(step_totals)

        # Create report
        report = TokenUsageReport(
            name=name,
            chunking=chunking,
            analysis={"chunks": analysis_chunks},
            issues_search=issues_search,
            deduplication=deduplication,
            validation=validation,
            step_totals=step_totals,
            total=grand_total,
        )

        logger.info("Token usage calculation complete!")
        return report

    def save_report(self, report: TokenUsageReport, output_path: Path) -> None:
        """Save report to JSON file."""
        output_path = Path(output_path)

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict and save
        report_dict = report.model_dump()

        with output_path.open("w") as f:
            json.dump(report_dict, f, indent=2)

        logger.info(f"Report saved to: {output_path}")


async def calculate_token_usage(review_dir: Path) -> None:
    """Calculate token usage metrics for a PR review.

    Args:
        review_dir: Path to the review directory containing metrics files
    """
    logger.info(f"Processing review directory: {review_dir}")

    # Initialize calculator
    calculator = TokenUsageCalculator(review_dir)

    # Calculate metrics
    report = calculator.calculate()

    # Save report
    output_path = review_dir / "total_token_count_metrics.json"
    calculator.save_report(report, output_path)
