from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BASE_URL = "https://api.speedcurve.com"
TEST_HISTORY_DAYS = 364
INCREMENTAL_LOOKBACK_SECONDS = 86400

RUM_EXPORT_ENDPOINT = "rum_export"
RUM_EXPORT_HISTORY_DAYS = 30
# Daily files are published after 05:00 UTC; wait one more hour before asking for the previous day.
RUM_EXPORT_READY_HOUR = 6
# The export endpoint allows 3 requests per minute.
RUM_EXPORT_REQUESTS_PER_SECOND = 3 / 60
RUM_EXPORT_CHUNK_SIZE = 5000


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
    RUM_EXPORT_ENDPOINT: SpeedcurveEndpoint(selector="download_url", primary_keys=("export_date", "export_row")),
}

# Exact column order of the caret-delimited export file, with the documented type of each column:
# https://support.speedcurve.com/reference/export-rum-data
RUM_EXPORT_COLUMNS: tuple[tuple[str, type], ...] = (
    ("page_id", int),
    ("session_id", int),
    ("epoch", int),
    ("account_id", int),
    ("page_label", str),
    ("url_unused", str),
    ("user_agent", str),
    ("browser_and_version", str),
    ("page_flags", int),
    ("continent", str),
    ("country", str),
    ("country_subdivision", str),
    ("city", str),
    ("external_script_count", int),
    ("blocking_external_script_count", int),
    ("stylesheet_count", int),
    ("blocking_stylesheet_count", int),
    ("font_count", int),
    ("image_above_the_fold_count", int),
    ("average_dom_depth", int),
    ("dom_element_count", int),
    ("viewport_width", int),
    ("viewport_height", int),
    ("document_width", int),
    ("document_height", int),
    ("navigation_start", int),
    ("redirect_start", int),
    ("redirect_end", int),
    ("fetch_start", int),
    ("domain_lookup_start", int),
    ("domain_lookup_end", int),
    ("connect_start", int),
    ("secure_connection_start", int),
    ("connect_end", int),
    ("request_start", int),
    ("response_start", int),
    ("response_end", int),
    ("dom_loading", int),
    ("dom_interactive", int),
    ("dom_content_loaded_event_start", int),
    ("dom_content_loaded_event_end", int),
    ("dom_complete", int),
    ("load_event_start", int),
    ("load_event_end", int),
    ("start_render", int),
    ("first_input_delay", int),
    ("long_tasks", str),
    ("interaction_type", str),
    ("interaction_time", int),
    ("interaction_element_selector", str),
    ("interaction_x_coordinate", int),
    ("interaction_y_coordinate", int),
    ("user_timing_name", str),
    ("user_timing_start", int),
    ("custom_data", str),
    ("device_type", str),
    ("image_count", int),
    ("document_transfer_size", int),
    ("connection_type", str),
    ("first_contentful_paint", int),
    ("inline_script_size", int),
    ("inline_style_size", int),
    ("device_memory", int),
    ("largest_contentful_paint", int),
    ("element_timing", str),
    ("cumulative_layout_shift", float),
    ("hostname", str),
    ("pathname", str),
    ("interaction_to_next_paint", int),
    ("inp_element_selector", str),
    ("inp_start_time", int),
    ("inp_input_delay", int),
    ("inp_processing_time", int),
    ("inp_presentation_delay", int),
    ("lcp_element_render_delay", int),
    ("lcp_element_selector", str),
    ("lcp_element_type", str),
    ("lcp_resource_load_delay", int),
    ("lcp_resource_load_time", int),
    ("cls_largest_entry_start_time", int),
    ("cls_largest_entry_value", float),
    ("delivery_type", str),
    ("operating_system", str),
    ("user_timing_duration", int),
    ("beacon_type", str),
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": field,
            "type": IncrementalFieldType.DateTime,
            "field": field,
            "field_type": IncrementalFieldType.Integer,
        }
    ]
    for name, field in (("tests", "timestamp"), ("deploys", "timestamp"), (RUM_EXPORT_ENDPOINT, "epoch"))
}
