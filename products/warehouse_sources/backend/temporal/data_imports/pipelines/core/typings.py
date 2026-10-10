from typing import NotRequired, TypedDict


class PipelineResult(TypedDict):
    """The import activity's report back to `ExternalDataJobWorkflow`.

    `consumer_manages_job_status` is the run-finalization ownership contract. Exactly one party
    writes the terminal job status, releases the v3 sync lock, and starts the post-import
    workflow:

    - False / absent (a fresh zero-batch run, and every failure path — an activity that raises
      returns no result): the workflow finalizes in its `finally` block.
    - True: the v3 load consumer finalizes after loading the final batch, and the workflow must
      keep its hands off all three.

    It is a runtime value, not a pure property of `ExternalDataJob.pipeline_version`, for one
    reason: a fresh v3 extraction that produced zero batches never notifies the load consumer, so
    the consumer cannot finalize a run it will never hear about — the workflow must. A zero-batch
    continuation instead appends a final marker to the earlier attempt's queued batches. The other producer of True,
    `import_data_sync`'s terminal-retry skip, is a run some other party already finalized, where
    True likewise means "workflow: hands off".
    Making this a pure version property requires an empty-final-batch queue message so the
    consumer hears about every v3 run.

    `fast_returned` marks a run completed on a negative source probe, before any extraction.
    It always rides with `skip_post_import_activities=True` (which does the actual skipping);
    the workflow reads it only to count these runs separately from other skipped ones.

    `handed_off` marks an attempt that left a worker which is shutting down. The import is not
    done: the workflow runs the activity again. Only an activity whose input says that hand-offs
    are free returns it. `handoff_attempts_used` is the Temporal attempt number that handed off,
    which the workflow adds up so the next execution continues the attempt numbers.
    """

    should_trigger_cdp_producer: bool
    consumer_manages_job_status: NotRequired[bool]
    skip_post_import_activities: NotRequired[bool]
    prepared_queryable_folder: NotRequired[str]
    fast_returned: NotRequired[bool]
    handed_off: NotRequired[bool]
    handoff_attempts_used: NotRequired[int]
