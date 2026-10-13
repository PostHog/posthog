from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

ENDPOINTS = {
    "surveys": "surveys",
    "questions": "surveys/{survey_id}/questions",
    "responses": "surveys/{survey_id}/responses",
}
INCREMENTAL_FIELDS = {"responses": [incremental_field("collected_at")]}
PRIMARY_KEYS = {
    "surveys": ["id"],
    "questions": ["survey_id", "id"],
    "responses": ["survey_id", "uuid"],
}
AUTH_ERRORS = {
    401: "Survicate rejected your API key. Check the key in Settings > Organization > Access Keys.",
    403: "Survicate denied API access. Check that your plan includes the Data Export API.",
}
