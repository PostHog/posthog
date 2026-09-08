import csv
import uuid
import zipfile
import datetime as dt
import tempfile
import dataclasses
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import structlog
from bingads.v13.reporting import ReportingDownloadException, ReportingDownloadParameters
from dateutil.relativedelta import relativedelta

from posthog.settings import integrations

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

from .schemas import BingAdsResource

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class BingAdsResumeConfig:
    """Resume state for Bing Ads stats report fetches.

    The stats endpoints iterate over yearly date-range chunks; the resume checkpoint captures
    the next chunk's start date and the original end of the sync window so a restart reuses
    the same window instead of drifting forward to today.
    """

    next_start_date: str
    end_date: str


ENVIRONMENT = "production"
REPORT_POLL_INTERVAL_MS = 5000


class BingAdsReportTimeoutError(Exception):
    """Bing did not finish generating a report inside the polling budget.

    The size of the requested date range drives the generation time, so callers can retry with a
    smaller range instead of replaying the same request.
    """


def parse_csv_to_dicts(csv_data: str) -> list[dict[str, Any]]:
    """Parse Bing Ads CSV report data into list of dictionaries."""
    if not csv_data or not csv_data.strip():
        return []

    # Remove BOM if present
    if csv_data.startswith("\ufeff"):
        csv_data = csv_data[1:]

    reader = csv.DictReader(csv_data.strip().split("\n"))

    # Convert "--" and empty strings to None
    return [{key: None if value in ("--", "") else value for key, value in row.items()} for row in reader]


def fetch_data_in_yearly_chunks(
    client: Any,
    resource: BingAdsResource,
    account_id: int,
    start_date: dt.date,
    end_date: dt.date,
    resumable_source_manager: ResumableSourceManager[BingAdsResumeConfig],
) -> Iterator[list[dict]]:
    """Fetch data in yearly chunks to handle Bing Ads API limitations.

    Bing Ads API performs better with smaller date ranges. This function splits
    large date ranges into yearly chunks and aggregates errors for better visibility.
    """
    # On resume, restart at the saved chunk boundary and preserve the original sync window
    # (end_date) so we don't drift if the worker restarts on a later day.
    if resumable_source_manager.can_resume() and (saved_state := resumable_source_manager.load_state()) is not None:
        start_date = dt.date.fromisoformat(saved_state.next_start_date)
        end_date = dt.date.fromisoformat(saved_state.end_date)

    def save_progress(next_start: dt.date) -> None:
        resumable_source_manager.save_state(
            BingAdsResumeConfig(
                next_start_date=next_start.isoformat(),
                end_date=end_date.isoformat(),
            )
        )

    current_start = start_date

    while current_start <= end_date:
        chunk_end = min(
            current_start + relativedelta(years=1),
            end_date,
        )

        try:
            # A narrowed chunk checkpoints each half it completes, so a worker restart resumes
            # after the last completed range instead of replaying a request that timed out.
            yield from _fetch_range_narrowing_on_timeout(
                client=client,
                resource=resource,
                account_id=account_id,
                range_start=current_start,
                range_end=chunk_end,
                on_range_complete=save_progress,
            )
        except Exception as e:
            # Bing's 36-month retention boundary moves day by day, so the oldest chunk can land just
            # outside it and get rejected with InvalidCustomDateRangeEnd. That rejection is
            # deterministic — skip the out-of-retention chunk (advancing the checkpoint past it)
            # instead of failing the whole sync. Any other error stays fatal so it can retry.
            if "InvalidCustomDateRangeEnd" not in str(e):
                raise
            logger.warning(
                "Skipping Bing Ads report chunk outside the 36-month retention window",
                resource=resource.value,
                chunk_start=current_start.isoformat(),
                chunk_end=chunk_end.isoformat(),
            )
            # No range completed, so the checkpoint must advance past the skipped chunk here.
            save_progress(chunk_end + dt.timedelta(days=1))

        # Move to the day after chunk_end to avoid duplicate dates at chunk boundaries
        current_start = chunk_end + dt.timedelta(days=1)


def _fetch_range_narrowing_on_timeout(
    client: Any,
    resource: BingAdsResource,
    account_id: int,
    range_start: dt.date,
    range_end: dt.date,
    on_range_complete: Callable[[dt.date], None],
) -> Iterator[list[dict]]:
    """Fetch one date range, halving it whenever Bing runs out of time to generate the report.

    Generation time grows with the range, so a range that times out can still succeed in halves.
    Replaying the same range would time out again and stall the sync forever. Ranges are fetched
    oldest first, and a single day that times out raises, because it cannot be narrowed further.

    `on_range_complete` gets the day after each range that completes. The oldest-first order keeps
    that date moving forward only, so the caller can save it as a resume checkpoint.
    """
    pending = [(range_start, range_end)]

    while pending:
        start, end = pending.pop()
        try:
            data_pages = client.get_data_by_resource(
                resource=resource,
                account_id=account_id,
                start_date=dt.datetime.combine(start, dt.time.min),
                end_date=dt.datetime.combine(end, dt.time.max),
            )
            for page in data_pages:
                if page:
                    yield page
        except BingAdsReportTimeoutError:
            if start >= end:
                raise
            midpoint = start + (end - start) // 2
            logger.warning(
                "Bing Ads report timed out, retrying the range in two halves",
                resource=resource.value,
                range_start=start.isoformat(),
                range_end=end.isoformat(),
                split_at=midpoint.isoformat(),
            )
            pending.append((midpoint + dt.timedelta(days=1), end))
            pending.append((start, midpoint))
        else:
            # Report progress only after the range's pages are yielded, so a resume re-attempts a
            # failed range rather than skipping past it.
            on_range_complete(end + dt.timedelta(days=1))


def build_report_request(
    service_factory: Any,
    report_config: dict,
    field_names: list[str],
    account_id: int,
    start_date: dt.datetime,
    end_date: dt.datetime,
) -> Any:
    """Build a Bing Ads report request object with all required configuration.

    The Bing Ads SDK uses a factory pattern to create report requests. This function
    encapsulates all the verbose setup into a single reusable function.
    """
    report_request = service_factory.create(report_config["report_type"])
    report_request.Aggregation = "Daily"
    report_request.ExcludeColumnHeaders = False
    report_request.ExcludeReportFooter = True
    report_request.ExcludeReportHeader = True
    report_request.Format = "Csv"
    report_request.ReturnOnlyCompleteData = False
    report_request.ReportName = report_config["report_name"]

    # Configure columns
    report_columns = service_factory.create(report_config["column_array_type"])
    setattr(report_columns, report_config["column_field"], field_names)
    report_request.Columns = report_columns

    # Configure scope
    scope = service_factory.create(report_config["scope_type"])
    scope.AccountIds = {"long": [account_id]}
    scope.Campaigns = None
    if report_config["scope_type"] == "AccountThroughAdGroupReportScope":
        scope.AdGroups = None
    report_request.Scope = scope

    # Configure date range
    report_time = service_factory.create("ReportTime")
    custom_date_range_start = service_factory.create("Date")
    custom_date_range_start.Day = start_date.day
    custom_date_range_start.Month = start_date.month
    custom_date_range_start.Year = start_date.year
    report_time.CustomDateRangeStart = custom_date_range_start

    custom_date_range_end = service_factory.create("Date")
    custom_date_range_end.Day = end_date.day
    custom_date_range_end.Month = end_date.month
    custom_date_range_end.Year = end_date.year
    report_time.CustomDateRangeEnd = custom_date_range_end

    report_request.Time = report_time

    return report_request


def download_and_extract_report_csv(
    reporting_service_manager: Any,
    report_request: Any,
    report_type: str,
    account_id: int,
) -> str:
    """Download report ZIP file and extract CSV content.

    Bing Ads Reporting API returns reports as ZIP files containing a single CSV.
    This function handles the download, extraction, and cleanup.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filename = f"{report_type}_{account_id}_{uuid.uuid4()}.zip"

        download_params = ReportingDownloadParameters(
            report_request=report_request,
            result_file_directory=tmpdir,
            result_file_name=filename,
            overwrite_result_file=True,
            timeout_in_milliseconds=integrations.BING_ADS_REPORT_TIMEOUT_SECONDS * 1000,
        )

        try:
            result_file_path = reporting_service_manager.download_file(download_params)
        except ReportingDownloadException as e:
            # The SDK raises this type only when a report is still not ready at the end of the
            # polling budget. A failed transfer raises FileDownloadException and a failed report
            # status raises ReportingException, so the type alone identifies the timeout. Do not
            # match on the message, because it is a hand-written SDK literal and not a contract.
            raise BingAdsReportTimeoutError(
                f"Bing Ads did not finish the {report_type} report within "
                f"{integrations.BING_ADS_REPORT_TIMEOUT_SECONDS}s"
            ) from e

        # Bing returns no file when the report completes with zero rows for the requested range
        # (e.g. a date window with no campaign activity). Treat that as an empty report instead of
        # crashing on Path(None).
        if result_file_path is None:
            return ""

        result_path = Path(result_file_path)
        with zipfile.ZipFile(result_path, "r") as zip_file:
            csv_files = [name for name in zip_file.namelist() if name.endswith(".csv")]
            if not csv_files:
                raise ValueError("No CSV file found in report ZIP")
            csv_data = zip_file.read(csv_files[0]).decode("utf-8")

    return csv_data
