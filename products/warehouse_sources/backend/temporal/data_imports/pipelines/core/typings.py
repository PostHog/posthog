from typing import NotRequired, TypedDict


class PipelineResult(TypedDict):
    should_trigger_cdp_producer: bool
    consumer_manages_job_status: NotRequired[bool]
    skip_post_import_activities: NotRequired[bool]
    prepared_queryable_folder: NotRequired[str]
