from typing import NotRequired, TypedDict


class PipelineResult(TypedDict):
    """The import activity's report back to `ExternalDataJobWorkflow`.

    `consumer_manages_job_status` is the run-finalization ownership contract. Exactly one party
    writes the terminal job status, releases the v3 sync lock, and starts the post-import
    workflow:

    - False / absent (v2, and every failure path — an activity that raises returns no result):
      the workflow finalizes in its `finally` block.
    - True: the v3 load consumer finalizes after loading the final batch, and the workflow must
      keep its hands off all three.

    It is a runtime value, not a pure property of `ExternalDataJob.pipeline_version`, for one
    reason: a v3 extraction that produced zero batches never notifies the load consumer, so the
    consumer cannot finalize a run it will never hear about — the workflow must. PipelineV3
    therefore reports True iff at least one batch reached the queue. The two other producers of
    True (`import_data_sync`'s terminal-retry skip, and the CDC-handled-externally path) are
    runs some other party already finalized, where True likewise means "workflow: hands off".
    Making this a pure version property requires an empty-final-batch queue message so the
    consumer hears about every v3 run — deferred until the v2 pipeline is deleted.
    """

    should_trigger_cdp_producer: bool
    consumer_manages_job_status: NotRequired[bool]
    skip_post_import_activities: NotRequired[bool]
    prepared_queryable_folder: NotRequired[str]
