from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://ywe3crmpll.execute-api.us-east-2.amazonaws.com/stage/"
API_DOCS_URL = "https://documenter.getpostman.com/view/35988189/2sA3XLEjFd"
PAGE_SIZE = 100

ENDPOINTS = {
    "customers": "customers",
    "jobs": "jobs",
    "estimates": "estimates",
    "invoices": "invoices",
    "payments": "payments",
    "projects": "projects",
    "users": "users",
    "job_status_workflows": "jobs/status-workflows",
    "job_status_workflow_statuses": "jobs/status-workflow-statuses",
    "pipeline_statuses": "pipeline-status",
    "lead_sources": "lead-source",
    "tags": "tags",
    "timesheets": "timesheets",
    "teams": "teams",
    "items": "items",
}
INCREMENTAL_ENDPOINTS = ("customers", "jobs", "estimates", "invoices", "payments", "projects")
INCREMENTAL_FIELDS = {name: [incremental_field("updated_at")] for name in INCREMENTAL_ENDPOINTS}
# The API reference lists no `page` parameter for these endpoints.
ENDPOINTS_WITHOUT_DOCUMENTED_PAGING = frozenset(
    {"users", "job_status_workflows", "job_status_workflow_statuses", "timesheets"}
)
PRIMARY_KEYS = ["id"]
AUTH_ERROR = "FieldPulse rejected the API key. Contact support@fieldpulse.com to check that your key is active."
