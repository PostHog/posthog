from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.speedcurve.com"
TEST_HISTORY_DAYS = 364
INCREMENTAL_LOOKBACK_SECONDS = 86400


@frozen
class SpeedcurveEndpoint:
    selector: str
    primary_keys: tuple[str, ...]
    paginated: bool = False


ENDPOINTS = {
    "sites": SpeedcurveEndpoint(selector="sites", primary_keys=("site_id",)),
    "urls": SpeedcurveEndpoint(selector="sites", primary_keys=("site_id", "url_id")),
    "tests": SpeedcurveEndpoint(selector="data", primary_keys=("test_id",), paginated=True),
    "deploys": SpeedcurveEndpoint(selector="deploys", primary_keys=("deploy_id",), paginated=True),
    "notes": SpeedcurveEndpoint(selector="notes", primary_keys=("note_id",)),
    "budgets": SpeedcurveEndpoint(selector="budgets", primary_keys=("budget_id",)),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.Integer,
        }
    ]
    for name in ("tests", "deploys")
}
