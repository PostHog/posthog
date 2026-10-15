from posthog.dataclasses import frozen


@frozen
class MezmoEndpoint:
    path: str
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)


ENDPOINTS: dict[str, MezmoEndpoint] = {
    "pipelines": MezmoEndpoint(path="pipeline", data_selector="data"),
    "alerts": MezmoEndpoint(
        path="pipeline/{pipeline_id}/alert", data_selector="data", primary_keys=("pipeline_id", "id")
    ),
    "pipeline_health": MezmoEndpoint(path="pipeline/health", data_selector="data.pipeline_health.pipelines"),
}

INVALID_KEY_MESSAGE = "Mezmo rejected your access key. Create a new IAM access key and reconnect."
PERMISSION_MESSAGE = (
    "Your Mezmo key needs read access to pipelines and alerts. Check its permissions and delegated account ID."
)
