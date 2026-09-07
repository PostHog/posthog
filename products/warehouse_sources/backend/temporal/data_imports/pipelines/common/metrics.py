from prometheus_client import Histogram

POST_LOAD_DURATION_SECONDS = Histogram(
    "warehouse_load_post_load_duration_seconds",
    "Duration of post-load operations",
    labelnames=["operation"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)
