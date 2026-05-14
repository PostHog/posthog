// AUTO-GENERATED from products/automl/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    AutomlPipelinesArchiveCreateParams,
    AutomlPipelinesCreateBody,
    AutomlPipelinesInferCreateParams,
    AutomlPipelinesListQueryParams,
    AutomlPipelinesModelVersionsActiveRetrieveParams,
    AutomlPipelinesModelVersionsActiveRetrieveQueryParams,
    AutomlPipelinesModelVersionsCreateBody,
    AutomlPipelinesModelVersionsCreateParams,
    AutomlPipelinesModelVersionsListParams,
    AutomlPipelinesModelVersionsListQueryParams,
    AutomlPipelinesModelVersionsPromoteCreateParams,
    AutomlPipelinesPartialUpdateBody,
    AutomlPipelinesPartialUpdateParams,
    AutomlPipelinesPauseCreateParams,
    AutomlPipelinesResumeCreateParams,
    AutomlPipelinesRetrainCreateParams,
    AutomlPipelinesRetrieveParams,
    AutomlPipelinesRunsListParams,
    AutomlPipelinesRunsListQueryParams,
    AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody,
    AutomlPipelinesRunsRecordBootstrapOutcomeCreateParams,
    AutomlPipelinesRunsRecordEdaResultCreateBody,
    AutomlPipelinesRunsRecordEdaResultCreateParams,
    AutomlPipelinesRunsRecordInferenceOutcomeCreateBody,
    AutomlPipelinesRunsRecordInferenceOutcomeCreateParams,
    AutomlPipelinesRunsRetrieveParams,
    AutomlPipelinesStartCreateParams,
    AutomlPipelinesValidateCreateBody,
} from '@/generated/automl/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AutomlArchiveSchema = AutomlPipelinesArchiveCreateParams.omit({ project_id: true })

const automlArchive = (): ToolBase<typeof AutomlArchiveSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-archive',
    schema: AutomlArchiveSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlArchiveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/archive/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlCreateSchema = AutomlPipelinesCreateBody.extend({
    name: AutomlPipelinesCreateBody.shape['name'].describe(
        'Human-readable label for the pipeline. Shows up in the UI and in property names. Keep it short and unique within the team.'
    ),
    task_type: AutomlPipelinesCreateBody.shape['task_type'].describe(
        'One of "clustering", "classification", "regression", or "forecasting". Determines what kind of model is trained and how predictions are surfaced.'
    ),
    config: AutomlPipelinesCreateBody.shape['config'].describe(
        'Task-type-specific configuration (target event, horizon, cluster count, forecasting window, etc.). Shape depends on task_type. See the AutoML design doc for per-task fields.'
    ),
    training_population: AutomlPipelinesCreateBody.shape['training_population'].describe(
        'Population definition (HogQL or filter spec) describing which persons, groups, or events are eligible to be drawn into the training set.'
    ),
    inference_population: AutomlPipelinesCreateBody.shape['inference_population'].describe(
        'Population definition describing who the model is scored against on each scheduled run. Usually broader than training_population.'
    ),
    inference_cadence: AutomlPipelinesCreateBody.shape['inference_cadence'].describe(
        'How often inference runs after the pipeline is active. One of "hourly", "daily", "weekly", "monthly", or "never" (manual only).'
    ),
    retraining_cadence: AutomlPipelinesCreateBody.shape['retraining_cadence'].describe(
        'How often the model is refit on a rolling window. One of "hourly", "daily", "weekly", "monthly", or "never".'
    ),
    autonomy: AutomlPipelinesCreateBody.shape['autonomy'].describe(
        'Output gate. "shadow_only" surfaces predictions internally but never writes person/group properties or emits events. "champion_only" writes from the active champion model. "promote_eligible" lets challenger models graduate to champion automatically when metrics pass thresholds.'
    ),
    output_property_name: AutomlPipelinesCreateBody.shape['output_property_name'].describe(
        'Name of the person or group property where predictions are written. Optional; if blank the pipeline emits events only.'
    ),
})

const automlCreate = (): ToolBase<typeof AutomlCreateSchema, Schemas.AutoMLPipelineDTO> => ({
    name: 'automl-create',
    schema: AutomlCreateSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.task_type !== undefined) {
            body['task_type'] = params.task_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.autonomy !== undefined) {
            body['autonomy'] = params.autonomy
        }
        if (params.inference_cadence !== undefined) {
            body['inference_cadence'] = params.inference_cadence
        }
        if (params.retraining_cadence !== undefined) {
            body['retraining_cadence'] = params.retraining_cadence
        }
        if (params.output_property_name !== undefined) {
            body['output_property_name'] = params.output_property_name
        }
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/`,
            body,
        })
        return result
    },
})

const AutomlGetRunSchema = AutomlPipelinesRunsRetrieveParams.omit({ project_id: true }).extend({
    id: AutomlPipelinesRunsRetrieveParams.shape['id'].describe(
        'Pipeline UUID. Used for URL routing; the run lookup is keyed by run_id + team.'
    ),
    run_id: AutomlPipelinesRunsRetrieveParams.shape['run_id'].describe(
        'Run UUID — comes from the bootstrap brief\'s "Run context" block. 404 if the run doesn\'t exist on this team.'
    ),
})

const automlGetRun = (): ToolBase<typeof AutomlGetRunSchema, Schemas.AutoMLPipelineRunDTO> => ({
    name: 'automl-get-run',
    schema: AutomlGetRunSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlGetRunSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineRunDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/runs/${encodeURIComponent(String(params.run_id))}/`,
        })
        return result
    },
})

const AutomlGetSchema = AutomlPipelinesRetrieveParams.omit({ project_id: true })

const automlGet = (): ToolBase<typeof AutomlGetSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-get',
    schema: AutomlGetSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlListSchema = AutomlPipelinesListQueryParams

const automlList = (): ToolBase<typeof AutomlListSchema, WithPostHogUrl<Schemas.PaginatedAutoMLPipelineDTOList>> => ({
    name: 'automl-list',
    schema: AutomlListSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoMLPipelineDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/automl/${item.id}`))
                ),
            },
            '/automl'
        )
    },
})

const AutomlPauseSchema = AutomlPipelinesPauseCreateParams.omit({ project_id: true })

const automlPause = (): ToolBase<typeof AutomlPauseSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-pause',
    schema: AutomlPauseSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlPauseSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/pause/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlGetActiveModelSchema = AutomlPipelinesModelVersionsActiveRetrieveParams.omit({ project_id: true })
    .extend(AutomlPipelinesModelVersionsActiveRetrieveQueryParams.shape)
    .extend({
        id: AutomlPipelinesModelVersionsActiveRetrieveParams.shape['id'].describe(
            'Pipeline UUID. The version is scoped to the pipeline — calling this against the wrong pipeline returns 404 even if a version with that role exists on another pipeline.'
        ),
        role: AutomlPipelinesModelVersionsActiveRetrieveQueryParams.shape['role'].describe(
            'Role to look up. One of "champion", "challenger", "archived". Defaults to "champion" if omitted.'
        ),
    })

const automlGetActiveModel = (): ToolBase<
    typeof AutomlGetActiveModelSchema,
    WithPostHogUrl<Schemas.AutoMLModelVersionDTO>
> => ({
    name: 'automl-get-active-model',
    schema: AutomlGetActiveModelSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlGetActiveModelSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLModelVersionDTO>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/model_versions/active/`,
            query: {
                role: params.role,
            },
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlRecordBootstrapOutcomeSchema = AutomlPipelinesRunsRecordBootstrapOutcomeCreateParams.omit({
    project_id: true,
})
    .extend(AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody.shape)
    .extend({
        id: AutomlPipelinesRunsRecordBootstrapOutcomeCreateParams.shape['id'].describe(
            'Pipeline UUID. Used for URL routing; the run lookup is keyed by run_id + team.'
        ),
        run_id: AutomlPipelinesRunsRecordBootstrapOutcomeCreateParams.shape['run_id'].describe(
            'Run UUID from the bootstrap brief\'s "Run context" block. Must be the currently in-flight run.'
        ),
        status: AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody.shape['status'].describe(
            'Terminal status to flip the run to. One of "succeeded" / "failed" / "aborted". Rejects "running" (open-state hint, not terminal).'
        ),
        outcome_report: AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody.shape['outcome_report'].describe(
            'Structured markdown body the user reads on the pipeline-detail page. Conventions: top-level Verdict line, Metrics table, Gate verdict, Leaderboard, Rows, Artifact, Reproducibility sections. Empty string when the run failed before producing meaningful output.'
        ),
        failure_reason: AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody.shape['failure_reason'].describe(
            'Compact tag categorizing the failure when status is failed or aborted. Examples: snapshot_fetch_failed / population_too_small / training_crash / mcp_unavailable / task_create_failed. Empty when status is succeeded.'
        ),
        cli_run_id: AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody.shape['cli_run_id'].describe(
            "The CLI's runs/<run_id>/ UTC timestamp (e.g. 20260514T130000Z). Pass through from the train step's output so the workspace path stays addressable from the run row alone. Optional."
        ),
        agent_session_id: AutomlPipelinesRunsRecordBootstrapOutcomeCreateBody.shape['agent_session_id'].describe(
            'Optional sandbox session id so we can replay the agent transcript later when debugging.'
        ),
    })

const automlRecordBootstrapOutcome = (): ToolBase<
    typeof AutomlRecordBootstrapOutcomeSchema,
    Schemas.AutoMLPipelineRunDTO
> => ({
    name: 'automl-record-bootstrap-outcome',
    schema: AutomlRecordBootstrapOutcomeSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlRecordBootstrapOutcomeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.outcome_report !== undefined) {
            body['outcome_report'] = params.outcome_report
        }
        if (params.failure_reason !== undefined) {
            body['failure_reason'] = params.failure_reason
        }
        if (params.cli_run_id !== undefined) {
            body['cli_run_id'] = params.cli_run_id
        }
        if (params.agent_session_id !== undefined) {
            body['agent_session_id'] = params.agent_session_id
        }
        const result = await context.api.request<Schemas.AutoMLPipelineRunDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/runs/${encodeURIComponent(String(params.run_id))}/record_bootstrap_outcome/`,
            body,
        })
        return result
    },
})

const AutomlRecordEdaResultSchema = AutomlPipelinesRunsRecordEdaResultCreateParams.omit({ project_id: true })
    .extend(AutomlPipelinesRunsRecordEdaResultCreateBody.shape)
    .extend({
        id: AutomlPipelinesRunsRecordEdaResultCreateParams.shape['id'].describe(
            'Pipeline UUID. Used for URL routing; the run lookup is keyed by run_id + team.'
        ),
        run_id: AutomlPipelinesRunsRecordEdaResultCreateParams.shape['run_id'].describe(
            'Run UUID from the bootstrap brief\'s "Run context" block. The run must be in "running" status.'
        ),
        eda_result: AutomlPipelinesRunsRecordEdaResultCreateBody.shape['eda_result'].describe(
            'Structured EDA summary from the CLI. Recommended keys (all optional, schemaless to allow CLI evolution): n_rows, n_cols, target_type (binary / multiclass / regression / none), class_balance (for classification), top_signal_features, drop_constant_or_near_constant, drop_redundant_keep_first, suspect_target_leakage, low_signal_features, eda_uri (full report path).'
        ),
        cli_run_id: AutomlPipelinesRunsRecordEdaResultCreateBody.shape['cli_run_id'].describe(
            "The CLI's runs/<run_id>/ UTC timestamp (e.g. 20260514T130000Z). Optional but recommended — lets the pipeline-detail page link directly into the workspace."
        ),
    })

const automlRecordEdaResult = (): ToolBase<typeof AutomlRecordEdaResultSchema, Schemas.AutoMLPipelineRunDTO> => ({
    name: 'automl-record-eda-result',
    schema: AutomlRecordEdaResultSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlRecordEdaResultSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.eda_result !== undefined) {
            body['eda_result'] = params.eda_result
        }
        if (params.cli_run_id !== undefined) {
            body['cli_run_id'] = params.cli_run_id
        }
        const result = await context.api.request<Schemas.AutoMLPipelineRunDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/runs/${encodeURIComponent(String(params.run_id))}/record_eda_result/`,
            body,
        })
        return result
    },
})

const AutomlRecordTrainingResultSchema = AutomlPipelinesModelVersionsCreateParams.omit({ project_id: true })
    .extend(AutomlPipelinesModelVersionsCreateBody.shape)
    .extend({
        id: AutomlPipelinesModelVersionsCreateParams.shape['id'].describe(
            'Pipeline UUID this training run belongs to. Versions are pipeline-scoped and never moved between pipelines.'
        ),
        run_id: AutomlPipelinesModelVersionsCreateBody.shape['run_id'].describe(
            'Run UUID from the bootstrap brief\'s "Run context" JSON block. Pass this so the new AutoMLModelVersion links onto the in-flight AutoMLPipelineRun row (sets created_model_version_id and writes a compact training_result summary). Optional — omitting it creates the version without linking, but you almost always want the link.'
        ),
        metrics: AutomlPipelinesModelVersionsCreateBody.shape['metrics'].describe(
            "Final evaluation metrics from the trainer (AutoGluon's leaderboard column names verbatim, e.g. accuracy / roc_auc / log_loss for classification). Used by the promotion gate."
        ),
        leaderboard: AutomlPipelinesModelVersionsCreateBody.shape['leaderboard'].describe(
            'Per-model leaderboard rows the trainer produced. List of dicts; shape is task-type-specific. Stored for audit and surfaced in the outcome report.'
        ),
        role: AutomlPipelinesModelVersionsCreateBody.shape['role'].describe(
            'One of "champion" / "challenger" / "archived". Defaults to "challenger". Pipelines have at most one champion + one challenger at a time (DB-enforced partial unique constraint).'
        ),
        training_params: AutomlPipelinesModelVersionsCreateBody.shape['training_params'].describe(
            'Parameters the trainer was invoked with — preset, time_limit_s, target column, training query. Round-tripped on the version for reproducibility.'
        ),
        artifact_uri: AutomlPipelinesModelVersionsCreateBody.shape['artifact_uri'].describe(
            'Pointer to the persisted model directory or archive (local path during dev, s3:// in production). Not validated by the API; the inference workflow will need it to load the model later.'
        ),
        features_hash: AutomlPipelinesModelVersionsCreateBody.shape['features_hash'].describe(
            'Short hash of the sorted feature column names. Used downstream to detect feature drift between training runs without diffing schemas.'
        ),
    })

const automlRecordTrainingResult = (): ToolBase<
    typeof AutomlRecordTrainingResultSchema,
    WithPostHogUrl<Schemas.AutoMLModelVersionDTO>
> => ({
    name: 'automl-record-training-result',
    schema: AutomlRecordTrainingResultSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlRecordTrainingResultSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.metrics !== undefined) {
            body['metrics'] = params.metrics
        }
        if (params.leaderboard !== undefined) {
            body['leaderboard'] = params.leaderboard
        }
        if (params.role !== undefined) {
            body['role'] = params.role
        }
        if (params.training_params !== undefined) {
            body['training_params'] = params.training_params
        }
        if (params.tracking_metadata !== undefined) {
            body['tracking_metadata'] = params.tracking_metadata
        }
        if (params.eval_metric !== undefined) {
            body['eval_metric'] = params.eval_metric
        }
        if (params.problem_type !== undefined) {
            body['problem_type'] = params.problem_type
        }
        if (params.artifact_uri !== undefined) {
            body['artifact_uri'] = params.artifact_uri
        }
        if (params.features_hash !== undefined) {
            body['features_hash'] = params.features_hash
        }
        if (params.rows_train !== undefined) {
            body['rows_train'] = params.rows_train
        }
        if (params.rows_val !== undefined) {
            body['rows_val'] = params.rows_val
        }
        if (params.rows_test !== undefined) {
            body['rows_test'] = params.rows_test
        }
        if (params.training_task_id !== undefined) {
            body['training_task_id'] = params.training_task_id
        }
        if (params.run_id !== undefined) {
            body['run_id'] = params.run_id
        }
        const result = await context.api.request<Schemas.AutoMLModelVersionDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/model_versions/`,
            body,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlListRunsSchema = AutomlPipelinesRunsListParams.omit({ project_id: true })
    .extend(AutomlPipelinesRunsListQueryParams.shape)
    .extend({
        id: AutomlPipelinesRunsListParams.shape['id'].describe(
            "Pipeline UUID. Returns 404 if the pipeline doesn't exist on the team."
        ),
    })

const automlListRuns = (): ToolBase<
    typeof AutomlListRunsSchema,
    WithPostHogUrl<Schemas.PaginatedAutoMLPipelineRunDTOList>
> => ({
    name: 'automl-list-runs',
    schema: AutomlListRunsSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlListRunsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoMLPipelineRunDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) => withPostHogUrl(context, item, `/automl/${item.id}`))
                ),
            },
            '/automl'
        )
    },
})

const AutomlListModelVersionsSchema = AutomlPipelinesModelVersionsListParams.omit({ project_id: true })
    .extend(AutomlPipelinesModelVersionsListQueryParams.shape)
    .extend({
        id: AutomlPipelinesModelVersionsListParams.shape['id'].describe(
            "Pipeline UUID. Returns 404 if the pipeline doesn't exist on the team."
        ),
    })

const automlListModelVersions = (): ToolBase<
    typeof AutomlListModelVersionsSchema,
    WithPostHogUrl<Schemas.PaginatedAutoMLModelVersionDTOList>
> => ({
    name: 'automl-list-model-versions',
    schema: AutomlListModelVersionsSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlListModelVersionsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAutoMLModelVersionDTOList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/model_versions/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlPromoteModelVersionSchema = AutomlPipelinesModelVersionsPromoteCreateParams.omit({
    project_id: true,
}).extend({
    id: AutomlPipelinesModelVersionsPromoteCreateParams.shape['id'].describe(
        'Pipeline UUID. Used for URL routing only — the actual lookup is by version_id + team, and a version can only be a champion on its own pipeline.'
    ),
    version_id: AutomlPipelinesModelVersionsPromoteCreateParams.shape['version_id'].describe(
        'UUID of the model version to promote. Must be a version on this pipeline; 404 otherwise.'
    ),
})

const automlPromoteModelVersion = (): ToolBase<
    typeof AutomlPromoteModelVersionSchema,
    WithPostHogUrl<Schemas.AutoMLModelVersionDTO>
> => ({
    name: 'automl-promote-model-version',
    schema: AutomlPromoteModelVersionSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlPromoteModelVersionSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLModelVersionDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/model_versions/${encodeURIComponent(String(params.version_id))}/promote/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlRetrainSchema = AutomlPipelinesRetrainCreateParams.omit({ project_id: true }).extend({
    id: AutomlPipelinesRetrainCreateParams.shape['id'].describe(
        'Pipeline UUID to retrain. Must be ACTIVE and have a winning run. Returns 409 with code=retrain_not_applicable otherwise.'
    ),
})

const automlRetrain = (): ToolBase<typeof AutomlRetrainSchema, WithPostHogUrl<Schemas.AutoMLPipelineRunDTO>> => ({
    name: 'automl-retrain',
    schema: AutomlRetrainSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlRetrainSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineRunDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/retrain/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlInferSchema = AutomlPipelinesInferCreateParams.omit({ project_id: true }).extend({
    id: AutomlPipelinesInferCreateParams.shape['id'].describe(
        'Pipeline UUID to score. Must be ACTIVE and have a winning run. Returns 409 with code=inference_not_applicable otherwise.'
    ),
})

const automlInfer = (): ToolBase<typeof AutomlInferSchema, WithPostHogUrl<Schemas.AutoMLPipelineRunDTO>> => ({
    name: 'automl-infer',
    schema: AutomlInferSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlInferSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineRunDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/infer/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlRecordInferenceOutcomeSchema = AutomlPipelinesRunsRecordInferenceOutcomeCreateParams.omit({
    project_id: true,
})
    .extend(AutomlPipelinesRunsRecordInferenceOutcomeCreateBody.shape)
    .extend({
        id: AutomlPipelinesRunsRecordInferenceOutcomeCreateParams.shape['id'].describe(
            'Pipeline UUID. Used for URL routing; the run lookup is keyed by run_id + team.'
        ),
        run_id: AutomlPipelinesRunsRecordInferenceOutcomeCreateParams.shape['run_id'].describe(
            'Run UUID from the inference brief\'s "Run context" block. Must be the currently in-flight run and must have run_kind=inference (otherwise 400).'
        ),
        status: AutomlPipelinesRunsRecordInferenceOutcomeCreateBody.shape['status'].describe(
            'Terminal status to flip the run to. One of "succeeded" / "failed" / "aborted". Rejects "running".'
        ),
        outcome_report: AutomlPipelinesRunsRecordInferenceOutcomeCreateBody.shape['outcome_report'].describe(
            'Short markdown body the user reads on the pipeline-detail page. Mention rows scored, predictions parquet URI, model run id, and any caveats. Empty string when the run failed before producing meaningful output.'
        ),
        inference_result: AutomlPipelinesRunsRecordInferenceOutcomeCreateBody.shape['inference_result'].describe(
            "The full JSON manifest from the CLI's `automl refresh-task` stdout — predictions_uri, predictions_count, id_column, model_uri, model_run_id, inference_run_id, rows, and any other fields the CLI emits. Pass through the parsed JSON object unchanged. The PostHog-side event- emission step reads predictions_uri out of this blob."
        ),
        failure_reason: AutomlPipelinesRunsRecordInferenceOutcomeCreateBody.shape['failure_reason'].describe(
            'Compact tag categorizing the failure when status is failed or aborted. Examples: snapshot_fetch_failed / model_load_failed / predict_crashed / mcp_unavailable. Empty when status is succeeded.'
        ),
        agent_session_id: AutomlPipelinesRunsRecordInferenceOutcomeCreateBody.shape['agent_session_id'].describe(
            'Optional sandbox session id so we can replay the agent transcript later when debugging.'
        ),
    })

const automlRecordInferenceOutcome = (): ToolBase<
    typeof AutomlRecordInferenceOutcomeSchema,
    Schemas.AutoMLPipelineRunDTO
> => ({
    name: 'automl-record-inference-outcome',
    schema: AutomlRecordInferenceOutcomeSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlRecordInferenceOutcomeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.outcome_report !== undefined) {
            body['outcome_report'] = params.outcome_report
        }
        if (params.inference_result !== undefined) {
            body['inference_result'] = params.inference_result
        }
        if (params.failure_reason !== undefined) {
            body['failure_reason'] = params.failure_reason
        }
        if (params.agent_session_id !== undefined) {
            body['agent_session_id'] = params.agent_session_id
        }
        const result = await context.api.request<Schemas.AutoMLPipelineRunDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/runs/${encodeURIComponent(String(params.run_id))}/record_inference_outcome/`,
            body,
        })
        return result
    },
})

const AutomlResumeSchema = AutomlPipelinesResumeCreateParams.omit({ project_id: true })

const automlResume = (): ToolBase<typeof AutomlResumeSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-resume',
    schema: AutomlResumeSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlResumeSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/resume/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlStartSchema = AutomlPipelinesStartCreateParams.omit({ project_id: true })

const automlStart = (): ToolBase<typeof AutomlStartSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-start',
    schema: AutomlStartSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlStartSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/start/`,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlUpdateSchema = AutomlPipelinesPartialUpdateParams.omit({ project_id: true }).extend(
    AutomlPipelinesPartialUpdateBody.shape
)

const automlUpdate = (): ToolBase<typeof AutomlUpdateSchema, WithPostHogUrl<Schemas.AutoMLPipelineDTO>> => ({
    name: 'automl-update',
    schema: AutomlUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.autonomy !== undefined) {
            body['autonomy'] = params.autonomy
        }
        if (params.inference_cadence !== undefined) {
            body['inference_cadence'] = params.inference_cadence
        }
        if (params.retraining_cadence !== undefined) {
            body['retraining_cadence'] = params.retraining_cadence
        }
        if (params.output_property_name !== undefined) {
            body['output_property_name'] = params.output_property_name
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.extra !== undefined) {
            body['extra'] = params.extra
        }
        const result = await context.api.request<Schemas.AutoMLPipelineDTO>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/automl/${result.id}`)
    },
})

const AutomlValidateSchema = AutomlPipelinesValidateCreateBody.extend({
    name: AutomlPipelinesValidateCreateBody.shape['name'].describe(
        'Human-readable label for the pipeline (only used by structural checks like output property name conventions). Use the same value you intend to pass to automl-create.'
    ),
    task_type: AutomlPipelinesValidateCreateBody.shape['task_type'].describe(
        'Task type the pipeline targets. Validation rules dispatch on this — classification runs the positive base-rate check, forecasting counts distinct series, clustering sanity-checks cluster_count against training-set size.'
    ),
    config: AutomlPipelinesValidateCreateBody.shape['config'].describe(
        'Task-type-specific configuration to validate. Classification expects target_event + horizon_days. Regression expects target_expression + horizon_days. Forecasting expects series_expression + grain + horizon_steps. Clustering accepts cluster_count.'
    ),
    training_population: AutomlPipelinesValidateCreateBody.shape['training_population'].describe(
        'Population definition to size for training. Only kind="hogql" populations are sized by data-touching checks; other shapes are accepted but flagged as not-counted.'
    ),
    inference_population: AutomlPipelinesValidateCreateBody.shape['inference_population'].describe(
        'Population definition used to estimate events-per-day output. Same kind="hogql" constraint as training_population.'
    ),
    inference_cadence: AutomlPipelinesValidateCreateBody.shape['inference_cadence'].describe(
        'How often inference runs. Used to project daily prediction event volume against the inference population size.'
    ),
    retraining_cadence: AutomlPipelinesValidateCreateBody.shape['retraining_cadence'].describe(
        'How often the model is refit. Compared against inference_cadence — info finding when retraining is more frequent than inference.'
    ),
    autonomy: AutomlPipelinesValidateCreateBody.shape['autonomy'].describe(
        "Output gate. Validation doesn't gate on autonomy itself; it's accepted as part of the request body so the same payload works for automl-create."
    ),
    output_property_name: AutomlPipelinesValidateCreateBody.shape['output_property_name'].describe(
        'Property name predictions are written to. Validation checks the naming convention (recommended "automl_" prefix; reserved "$" prefix is blocked).'
    ),
})

const automlValidate = (): ToolBase<typeof AutomlValidateSchema, Schemas.ValidationReport> => ({
    name: 'automl-validate',
    schema: AutomlValidateSchema,
    handler: async (context: Context, params: z.infer<typeof AutomlValidateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.task_type !== undefined) {
            body['task_type'] = params.task_type
        }
        if (params.config !== undefined) {
            body['config'] = params.config
        }
        if (params.training_population !== undefined) {
            body['training_population'] = params.training_population
        }
        if (params.inference_population !== undefined) {
            body['inference_population'] = params.inference_population
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.autonomy !== undefined) {
            body['autonomy'] = params.autonomy
        }
        if (params.inference_cadence !== undefined) {
            body['inference_cadence'] = params.inference_cadence
        }
        if (params.retraining_cadence !== undefined) {
            body['retraining_cadence'] = params.retraining_cadence
        }
        if (params.output_property_name !== undefined) {
            body['output_property_name'] = params.output_property_name
        }
        const result = await context.api.request<Schemas.ValidationReport>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/automl_pipelines/validate/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'automl-archive': automlArchive,
    'automl-create': automlCreate,
    'automl-get-run': automlGetRun,
    'automl-get': automlGet,
    'automl-list': automlList,
    'automl-pause': automlPause,
    'automl-get-active-model': automlGetActiveModel,
    'automl-record-bootstrap-outcome': automlRecordBootstrapOutcome,
    'automl-record-eda-result': automlRecordEdaResult,
    'automl-record-training-result': automlRecordTrainingResult,
    'automl-list-runs': automlListRuns,
    'automl-list-model-versions': automlListModelVersions,
    'automl-promote-model-version': automlPromoteModelVersion,
    'automl-retrain': automlRetrain,
    'automl-infer': automlInfer,
    'automl-record-inference-outcome': automlRecordInferenceOutcome,
    'automl-resume': automlResume,
    'automl-start': automlStart,
    'automl-update': automlUpdate,
    'automl-validate': automlValidate,
}
