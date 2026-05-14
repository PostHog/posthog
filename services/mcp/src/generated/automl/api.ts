/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 18 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List non-archived pipelines for the team, newest first.
 */
export const AutomlPipelinesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a new pipeline in draft state.
 */
export const AutomlPipelinesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string(),
        task_type: zod
            .enum(['clustering', 'classification', 'regression', 'forecasting'])
            .describe(
                '* `clustering` - CLUSTERING\n* `classification` - CLASSIFICATION\n* `regression` - REGRESSION\n* `forecasting` - FORECASTING'
            ),
        config: zod.record(zod.string(), zod.unknown()),
        training_population: zod.record(zod.string(), zod.unknown()),
        inference_population: zod.record(zod.string(), zod.unknown()),
        description: zod.string().optional(),
        autonomy: zod
            .enum(['shadow_only', 'champion_only', 'promote_eligible'])
            .optional()
            .describe(
                '* `shadow_only` - SHADOW_ONLY\n* `champion_only` - CHAMPION_ONLY\n* `promote_eligible` - PROMOTE_ELIGIBLE'
            ),
        inference_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '* `hourly` - HOURLY\n* `daily` - DAILY\n* `weekly` - WEEKLY\n* `monthly` - MONTHLY\n* `never` - NEVER'
            ),
        retraining_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '* `hourly` - HOURLY\n* `daily` - DAILY\n* `weekly` - WEEKLY\n* `monthly` - MONTHLY\n* `never` - NEVER'
            ),
        output_property_name: zod.string().optional(),
    })
    .describe(
        "Request body for ``POST /automl_pipelines/``.\n\n``team_id`` and ``created_by_id`` are injected by the view from the\nrequest scope and aren't part of the DTO."
    )

/**
 * Get one pipeline by ID.
 */
export const AutomlPipelinesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Apply partial config updates. Use start / pause / resume / archive for status transitions.
 */
export const AutomlPipelinesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().nullish(),
        description: zod.string().nullish(),
        autonomy: zod
            .union([
                zod
                    .enum(['shadow_only', 'champion_only', 'promote_eligible'])
                    .describe(
                        '* `shadow_only` - SHADOW_ONLY\n* `champion_only` - CHAMPION_ONLY\n* `promote_eligible` - PROMOTE_ELIGIBLE'
                    ),
                zod.null(),
            ])
            .optional(),
        inference_cadence: zod
            .union([
                zod
                    .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
                    .describe(
                        '* `hourly` - HOURLY\n* `daily` - DAILY\n* `weekly` - WEEKLY\n* `monthly` - MONTHLY\n* `never` - NEVER'
                    ),
                zod.null(),
            ])
            .optional(),
        retraining_cadence: zod
            .union([
                zod
                    .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
                    .describe(
                        '* `hourly` - HOURLY\n* `daily` - DAILY\n* `weekly` - WEEKLY\n* `monthly` - MONTHLY\n* `never` - NEVER'
                    ),
                zod.null(),
            ])
            .optional(),
        output_property_name: zod.string().nullish(),
        config: zod.record(zod.string(), zod.unknown()).nullish(),
        training_population: zod.record(zod.string(), zod.unknown()).nullish(),
        inference_population: zod.record(zod.string(), zod.unknown()).nullish(),
        extra: zod.record(zod.string(), zod.unknown()).optional(),
    })
    .describe(
        'Request body for ``PATCH /automl_pipelines/{id}/``.\n\nAll fields are optional; ``None`` means leave unchanged. Status\ntransitions go through the dedicated start / pause / resume / archive\nactions instead of this endpoint.'
    )

/**
 * Soft-archive a pipeline. Inference stops; history is preserved.
 */
export const AutomlPipelinesArchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List every trained model version on a pipeline, newest first.

Archived versions are included — they're the audit trail and the
``$model_version_id`` on past prediction events still needs to resolve.
 */
export const AutomlPipelinesModelVersionsListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesModelVersionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Persist a completed training run as a new model version.

Always recorded as ``challenger`` by default — promotion to champion is
the explicit ``promote`` action below. Called by the bootstrap and
retraining agents from inside their sandbox after the trainer returns.

When the request body carries a ``run_id``, the matching
``AutoMLPipelineRun`` is updated in the same transaction so the
pipeline-detail timeline links the new version to the run that
produced it. Agents pull ``run_id`` from the bootstrap brief's
Run context block.
 */
export const AutomlPipelinesModelVersionsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesModelVersionsCreateBody = /* @__PURE__ */ zod
    .object({
        metrics: zod.record(zod.string(), zod.unknown()),
        leaderboard: zod.array(zod.record(zod.string(), zod.unknown())),
        role: zod
            .enum(['champion', 'challenger', 'archived'])
            .optional()
            .describe('* `champion` - CHAMPION\n* `challenger` - CHALLENGER\n* `archived` - ARCHIVED'),
        training_params: zod.record(zod.string(), zod.unknown()).optional(),
        tracking_metadata: zod.record(zod.string(), zod.unknown()).optional(),
        eval_metric: zod.string().optional(),
        problem_type: zod.string().optional(),
        artifact_uri: zod.string().optional(),
        features_hash: zod.string().optional(),
        rows_train: zod.number().nullish(),
        rows_val: zod.number().nullish(),
        rows_test: zod.number().nullish(),
        training_task_id: zod.uuid().nullish(),
        run_id: zod.uuid().nullish(),
    })
    .describe(
        'Request body for ``POST /automl_pipelines/{id}/model_versions/``.\n\nCalled by the bootstrap / retraining agent when a training run finishes.\n``role`` defaults to ``challenger`` so a fresh run never auto-displaces the\nexisting champion — promotion is a separate explicit step.'
    )

/**
 * Make ``version_id`` the champion for its pipeline.

Atomic: the prior champion (if any) is archived in the same transaction
the target is set to champion. Idempotent — promoting an existing
champion is a no-op. Returns 404 if the version doesn't belong to the
team or pipeline.
 */
export const AutomlPipelinesModelVersionsPromoteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    version_id: zod.string(),
})

/**
 * Get the model version currently holding a role on a pipeline.

The partial unique constraint guarantees at most one champion and one
challenger per pipeline. Returns 404 when no version holds the role —
the most common cause is a pipeline that hasn't completed bootstrap yet.
 */
export const AutomlPipelinesModelVersionsActiveRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesModelVersionsActiveRetrieveQueryParams = /* @__PURE__ */ zod.object({
    role: zod
        .string()
        .optional()
        .describe("Role to look up. Defaults to 'champion'. One of: champion, challenger, archived."),
})

/**
 * Pause scheduled inference / training for the pipeline.
 */
export const AutomlPipelinesPauseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Resume a paused pipeline.
 */
export const AutomlPipelinesResumeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Dispatch a retraining iteration on an active pipeline.

The pipeline must be ``ACTIVE`` and have a winning run to iterate on
(bootstrap must have landed a champion first). Opens a new
``AutoMLPipelineRun(run_kind=RETRAIN)`` chained via ``parent_run_id``
to the previous winning run, then enqueues a Task that runs the
``automl-retrain`` agent skill inside the AutoML sandbox.

Returns the new run DTO. Pipeline status stays ``ACTIVE`` — retraining
failures don't fail the pipeline (the existing champion keeps serving).
 */
export const AutomlPipelinesRetrainCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List every run (bootstrap / retrain / inference) for a pipeline, newest first.

Includes terminal runs (succeeded / failed / aborted) — the pipeline-detail
timeline surfaces the full history. Returns 200 with an empty list if the
pipeline has no runs yet (e.g. before ``start`` is called for the first time).
 */
export const AutomlPipelinesRunsListParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get one pipeline run by id.

Used by the bootstrap agent to look up its own run mid-flight (e.g. to
confirm a previous ``record_eda_result`` write landed before continuing).
 */
export const AutomlPipelinesRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string(),
})

/**
 * Flip a run to a terminal state and write the agent's final outcome report.

Single-shot — once a run reaches a terminal state, re-calling this no-ops
(returns the already-terminal DTO). Lets the agent retry the MCP call
after a transient network blip without overwriting the timeline.
Rejects ``status='running'`` with 400 (terminal status required).
 */
export const AutomlPipelinesRunsRecordBootstrapOutcomeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string(),
})

export const AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['running', 'succeeded', 'failed', 'aborted'])
            .describe('* `running` - RUNNING\n* `succeeded` - SUCCEEDED\n* `failed` - FAILED\n* `aborted` - ABORTED'),
        outcome_report: zod.string(),
        failure_reason: zod.string().optional(),
        cli_run_id: zod.string().optional(),
        agent_session_id: zod.string().optional(),
    })
    .describe(
        'Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_bootstrap_outcome/``.\n\nCalled by the bootstrap agent as the final checkpoint of a run. Flips the\nrun to a terminal status and writes the structured markdown outcome report\nsurfaced on the pipeline-detail page.'
    )

/**
 * Stash the agent's EDA output on an in-progress run.

Called by the bootstrap agent between ``automl eda`` and ``automl train``.
Status stays at ``running`` — EDA is a mid-run checkpoint, not terminal.
Idempotent in the sense that a second call overwrites the prior payload
(the CLI's ``eda.yaml`` is regenerated on every re-run).
 */
export const AutomlPipelinesRunsRecordEdaResultCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string(),
})

export const AutomlPipelinesRunsRecordEdaResultCreateBody = /* @__PURE__ */ zod
    .object({
        eda_result: zod.record(zod.string(), zod.unknown()),
        cli_run_id: zod.string().optional(),
    })
    .describe(
        "Request body for ``POST /automl_pipelines/{id}/runs/{run_id}/record_eda_result/``.\n\nCalled by the bootstrap agent between ``automl eda`` and ``automl train``.\nThe ``eda_result`` payload is schemaless on purpose so the CLI's\n``eda.yaml`` shape can evolve without forcing a migration."
    )

/**
 * Transition a draft pipeline to bootstrap-pending and enqueue the first training run.

The training itself runs in a sandbox via the ``tasks`` product (one
Task per pipeline bootstrap). The task id lands on the pipeline as
``runtime.bootstrap_task_id`` so the agent's progress is traceable.
 */
export const AutomlPipelinesStartCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Run preflight validation against a proposed pipeline config.

Side-effect-free: nothing is written, no pipeline is created. Same body
shape as the create endpoint; call this first so the user can see the
validation report (volume, base rate, leakage warnings, sample plan)
before committing to a pipeline.
 */
export const AutomlPipelinesValidateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutomlPipelinesValidateCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string(),
        task_type: zod
            .enum(['clustering', 'classification', 'regression', 'forecasting'])
            .describe(
                '* `clustering` - CLUSTERING\n* `classification` - CLASSIFICATION\n* `regression` - REGRESSION\n* `forecasting` - FORECASTING'
            ),
        config: zod.record(zod.string(), zod.unknown()),
        training_population: zod.record(zod.string(), zod.unknown()),
        inference_population: zod.record(zod.string(), zod.unknown()),
        description: zod.string().optional(),
        autonomy: zod
            .enum(['shadow_only', 'champion_only', 'promote_eligible'])
            .optional()
            .describe(
                '* `shadow_only` - SHADOW_ONLY\n* `champion_only` - CHAMPION_ONLY\n* `promote_eligible` - PROMOTE_ELIGIBLE'
            ),
        inference_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '* `hourly` - HOURLY\n* `daily` - DAILY\n* `weekly` - WEEKLY\n* `monthly` - MONTHLY\n* `never` - NEVER'
            ),
        retraining_cadence: zod
            .enum(['hourly', 'daily', 'weekly', 'monthly', 'never'])
            .optional()
            .describe(
                '* `hourly` - HOURLY\n* `daily` - DAILY\n* `weekly` - WEEKLY\n* `monthly` - MONTHLY\n* `never` - NEVER'
            ),
        output_property_name: zod.string().optional(),
    })
    .describe(
        "Request body for ``POST /automl_pipelines/``.\n\n``team_id`` and ``created_by_id`` are injected by the view from the\nrequest scope and aren't part of the DTO."
    )
