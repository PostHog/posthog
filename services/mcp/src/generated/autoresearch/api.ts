/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 29 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const AutoresearchListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const AutoresearchCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchCreateBodyNameMax = 255

export const autoresearchCreateBodyTargetEventMax = 255

export const autoresearchCreateBodyHorizonDaysMin = -2147483648
export const autoresearchCreateBodyHorizonDaysMax = 2147483647

export const autoresearchCreateBodyTrainingLookbackDaysMin = -2147483648
export const autoresearchCreateBodyTrainingLookbackDaysMax = 2147483647

export const autoresearchCreateBodyCadenceDaysMin = -2147483648
export const autoresearchCreateBodyCadenceDaysMax = 2147483647

export const autoresearchCreateBodyIterationBudgetMin = -2147483648
export const autoresearchCreateBodyIterationBudgetMax = 2147483647

export const autoresearchCreateBodyPlateauIterationsMin = -2147483648
export const autoresearchCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchCreateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchCreateBodyTargetEventMax)
        .optional()
        .describe(
            "PostHog event name to predict, e.g. '$pageview' or 'signed_up'. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .looseObject({})
        .optional()
        .describe('Full target definition. Can be left empty to use target_event alone.'),
    horizon_days: zod
        .number()
        .min(autoresearchCreateBodyHorizonDaysMin)
        .max(autoresearchCreateBodyHorizonDaysMax)
        .optional()
        .describe('Prediction horizon in days. The model predicts whether the target event occurs within this window.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples. Larger windows give more data but may include stale behavior. Default: 180.'
        ),
    training_population: zod
        .looseObject({})
        .optional()
        .describe('Training population filter. Use {} for all identified users.'),
    inference_population: zod
        .looseObject({})
        .optional()
        .describe('Inference population filter. Defaults to training_population if not set.'),
    cadence_days: zod
        .number()
        .min(autoresearchCreateBodyCadenceDaysMin)
        .max(autoresearchCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days. Default: 1.'),
    iteration_budget: zod
        .number()
        .min(autoresearchCreateBodyIterationBudgetMin)
        .max(autoresearchCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop. Default: 50.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchCreateBodyPlateauIterationsMin)
        .max(autoresearchCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations. Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score. Auto-derived from target_event if omitted, e.g. 'predicted_p_pageview'."
        ),
})

/**
 * List and retrieve champion/challenger models for a pipeline.
 *
 * Models are the persisted artifacts produced by training runs. Each model
 * holds a portable recipe (feature SQL, transforms, model class, params) that
 * the daily inference workflow compiles to score users.
 */
export const AutoresearchModelsListParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchModelsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * List and retrieve champion/challenger models for a pipeline.
 *
 * Models are the persisted artifacts produced by training runs. Each model
 * holds a portable recipe (feature SQL, transforms, model class, params) that
 * the daily inference workflow compiles to score users.
 */
export const AutoresearchModelsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch model.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List and retrieve inference, validation, and notebook runs for a pipeline.
 */
export const AutoresearchRunsListParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * List steering suggestions for a pipeline, ordered most recent first. Check 'status' to see which have been picked up or acted on by the agent.
 * @summary List suggestions
 */
export const AutoresearchSuggestionsListParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchSuggestionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Inject a free-text hypothesis or direction into a running pipeline. The sandbox agent reads queued suggestions at the start of each iteration batch and decides: translate into a concrete iteration ('acted_on'), apply as a search constraint ('picked_up'), or reject with rationale ('dismissed'). Use priority='try_next' to instruct the agent to act on this before autonomous iterations; 'consider' is advisory. Check 'agent_response' after the next training run to see how the suggestion was interpreted.
 * @summary Submit a suggestion
 */
export const AutoresearchSuggestionsCreateParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchSuggestionsCreateBodyPromptMax = 2000

export const autoresearchSuggestionsCreateBodyPriorityDefault = `consider`

export const AutoresearchSuggestionsCreateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .string()
        .max(autoresearchSuggestionsCreateBodyPromptMax)
        .describe(
            "Free-text hypothesis or direction for the agent to explore, e.g. 'try a tree-based model' or 'remove recency features, I suspect leakage'."
        ),
    priority: zod
        .enum(['try_next', 'consider'])
        .describe('* `try_next` - try_next\n* `consider` - consider')
        .default(autoresearchSuggestionsCreateBodyPriorityDefault)
        .describe(
            "'try_next' asks the agent to act on this before other autonomous iterations; 'consider' is advisory context.\n\n* `try_next` - try_next\n* `consider` - consider"
        ),
})

/**
 * Get details for a specific suggestion including its status and agent_response.
 * @summary Get suggestion
 */
export const AutoresearchSuggestionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch suggestion.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Record how the agent handled a steering suggestion: set status to 'picked_up' (applied as a search constraint), 'acted_on' (spawned iterations), or 'dismissed' (rejected — explain in agent_response), and write the agent_response note the human will read. Call this from the training loop after deciding what to do with a pending suggestion. Recording an iteration with parent_suggestion set already advances a suggestion to 'acted_on'; use this to add the narrative or to mark a suggestion picked_up/dismissed without spawning an iteration.
 * @summary Respond to a suggestion
 */
export const AutoresearchSuggestionsRespondCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch suggestion.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchSuggestionsRespondCreateBodyAgentResponseDefault = ``
export const autoresearchSuggestionsRespondCreateBodyAgentResponseMax = 2000

export const AutoresearchSuggestionsRespondCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['picked_up', 'acted_on', 'dismissed'])
            .describe('* `picked_up` - picked_up\n* `acted_on` - acted_on\n* `dismissed` - dismissed')
            .describe(
                "How the agent handled the suggestion: 'picked_up' (applied as a search constraint), 'acted_on' (spawned one or more iterations), or 'dismissed' (rejected — explain why in agent_response).\n\n* `picked_up` - picked_up\n* `acted_on` - acted_on\n* `dismissed` - dismissed"
            ),
        agent_response: zod
            .string()
            .max(autoresearchSuggestionsRespondCreateBodyAgentResponseMax)
            .default(autoresearchSuggestionsRespondCreateBodyAgentResponseDefault)
            .describe(
                'Plain-English note on how the suggestion was interpreted and acted upon (or why it was dismissed).'
            ),
    })
    .describe('Input for the agent to record how it interpreted a steering suggestion.')

/**
 * List, retrieve, open, record iterations into, and complete training runs for a pipeline.
 *
 * The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
 * training run directly — recording each iteration as it completes rather than via a single
 * terminal sandbox output. Recipe validation and champion promotion stay server-side.
 */
export const AutoresearchTrainingRunsListParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchTrainingRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Open a new training run for a pipeline and return its id. An agent — the in-house sandbox, an external bring-your-own agent, or a scheduled job — then records iterations against this run and finalizes it with the complete endpoint. The run starts in 'running'.
 * @summary Open a training run
 */
export const AutoresearchTrainingRunsCreateParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainingRunsCreateBodyIterationBudgetMax = 500

export const AutoresearchTrainingRunsCreateBody = /* @__PURE__ */ zod
    .object({
        iteration_budget: zod
            .number()
            .min(1)
            .max(autoresearchTrainingRunsCreateBodyIterationBudgetMax)
            .optional()
            .describe("Iteration budget for this run. Defaults to the pipeline's iteration_budget if omitted."),
    })
    .describe('Input for opening an agent-driven training run.')

/**
 * List the files an agent has uploaded for this training run's artifact bundle (train.py, predict.py, features.sql, and any eda/ notebooks).
 * @summary List artifact bundle files
 */
export const AutoresearchTrainingRunsArtifactsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Remove one file from this training run's artifact bundle. Idempotent — deleting a missing file is a no-op.
 * @summary Delete an artifact bundle file
 */
export const AutoresearchTrainingRunsArtifactsDeleteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainingRunsArtifactsDeleteCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsDeleteCreateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsDeleteCreateBodyPathMax)
            .describe("Relative path of the file within the bundle, e.g. 'train.py'."),
    })
    .describe('Input for fetching or deleting one bundle file by path.')

/**
 * Fetch one file from this training run's artifact bundle, base64-encoded.
 * @summary Get an artifact bundle file
 */
export const AutoresearchTrainingRunsArtifactsGetCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainingRunsArtifactsGetCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsGetCreateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsGetCreateBodyPathMax)
            .describe("Relative path of the file within the bundle, e.g. 'train.py'."),
    })
    .describe('Input for fetching or deleting one bundle file by path.')

/**
 * Upload one file of this training run's artifact bundle. Send the file contents base64-encoded in content_base64. Re-uploading the same path overwrites it. Use this — not curl/set_output — to author train.py, predict.py, and features.sql.
 * @summary Upload an artifact bundle file
 */
export const AutoresearchTrainingRunsArtifactsUploadCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainingRunsArtifactsUploadCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsUploadCreateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsUploadCreateBodyPathMax)
            .describe(
                "Relative path within the bundle, e.g. 'train.py', 'predict.py', 'features.sql', or 'eda/iter-3-gbm.ipynb'. Segments are limited to [A-Za-z0-9_.-]; absolute paths and '..' traversal are rejected."
            ),
        content_base64: zod
            .string()
            .describe(
                'File contents, base64-encoded. Decoded server-side and written to object storage. Max 10 MB decoded.'
            ),
    })
    .describe("Input for uploading one file of a training run's artifact bundle.")

/**
 * Finalize a training run. The backend selects the best iteration (highest holdout score, or the one you name), decides champion vs challenger via the promotion ladder, and persists the model. Agents cannot set the champion directly — promotion is server-side.
 * @summary Complete a training run
 */
export const AutoresearchTrainingRunsCompleteCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainingRunsCompleteCreateBodyRecommendedNextDefault = ``
export const autoresearchTrainingRunsCompleteCreateBodyDistillationDefault = ``

export const AutoresearchTrainingRunsCompleteCreateBody = /* @__PURE__ */ zod
    .object({
        best_iteration_id: zod
            .string()
            .nullish()
            .describe(
                'Iteration to promote as champion candidate. If omitted, the kept iteration with the highest holdout_score is used.'
            ),
        model_explanation: zod
            .looseObject({})
            .optional()
            .describe('Global feature importance / directionality bundle for the champion model card.'),
        recommended_next: zod
            .string()
            .default(autoresearchTrainingRunsCompleteCreateBodyRecommendedNextDefault)
            .describe(
                'What a future run should try next, given what this run learned. Stored in the run summary so the next run reads it during orientation. Keep it short and concrete.'
            ),
        distillation: zod
            .string()
            .default(autoresearchTrainingRunsCompleteCreateBodyDistillationDefault)
            .describe(
                'A 1–2 sentence distillation of what this run learned — the winning signal, the key transform, the dead-ends. Stored in the run summary as the cheapest thing the next run reads.'
            ),
    })
    .describe('Input for finalizing a training run. The backend selects/promotes the champion.')

/**
 * Record one iteration of an open training run. Idempotent on iteration_number — re-sending the same number updates that iteration. The recipe is validated server-side: model_class must be in the allowlist and feature_sql must be a read-only SELECT keyed on person_id.
 * @summary Record a training iteration
 */
export const AutoresearchTrainingRunsIterationsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin = 0

export const autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault = ``
export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax = 1

export const AutoresearchTrainingRunsIterationsCreateBody = /* @__PURE__ */ zod
    .object({
        iteration_number: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin)
            .describe(
                'Zero-based index of this iteration within the run. Re-sending the same number updates that iteration (idempotent).'
            ),
        recipe_snapshot: zod
            .looseObject({})
            .describe(
                'Compact recipe for this iteration: feature_sql (HogQL SELECT keyed on person_id) and transforms.'
            ),
        model_spec: zod
            .looseObject({})
            .describe('model_class (must be allowlisted) and model_params tried this iteration.'),
        status: zod
            .enum(['kept', 'discarded', 'crashed'])
            .describe('* `kept` - kept\n* `discarded` - discarded\n* `crashed` - crashed')
            .describe(
                "'kept' if this iteration improved on the best score, 'discarded' otherwise, 'crashed' on failure.\n\n* `kept` - kept\n* `discarded` - discarded\n* `crashed` - crashed"
            ),
        train_score: zod.number().nullish().describe('Training-set AUC for this iteration.'),
        holdout_score: zod
            .number()
            .nullish()
            .describe('Held-out AUC for this iteration. Used to pick the champion at completion.'),
        agent_description: zod
            .string()
            .default(autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault)
            .describe("Agent's plain-English rationale for this iteration."),
        agent_confidence: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax)
            .nullish()
            .describe("Agent's self-assessed confidence (0–1) that this iteration helps."),
        parent_suggestion: zod
            .string()
            .nullish()
            .describe(
                "UUID of the steering suggestion this iteration was spawned from, if any. Set it whenever the iteration acts on a pending suggestion — it links the iteration back to the suggestion for attribution and advances the suggestion to 'acted_on'."
            ),
    })
    .describe('Input for recording one training iteration. Validated against the recipe allowlist.')

/**
 * Run features_sql server-side against the labeled training population and write the resulting train/holdout feature and label parquet files directly into this run's sandbox. Returns the local sandbox paths, row counts, and feature columns. The rows never pass through the agent's context and there is no 500-row cap. Read the returned paths with pd.read_parquet and iterate in Python.
 * @summary Materialize training features to the sandbox
 */
export const AutoresearchTrainingRunsMaterializeFeaturesCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchTrainingRunsMaterializeFeaturesCreateBody = /* @__PURE__ */ zod
    .object({
        features_sql: zod
            .string()
            .describe(
                'Your HogQL feature query, using the {anchors}/{lookback_days} contract. Must be a read-only SELECT keyed on person_id (aliased to distinct_id), one row per user. The backend runs it server-side against the labeled training population — no 500-row cap — and writes the resulting train/holdout feature and label parquet files into your sandbox.'
            ),
    })
    .describe("Input for materializing the labeled training feature matrix into the run's sandbox.")

/**
 * Return recent completed training runs and their iteration trails so a new run can learn from what was already tried. Scoped to this pipeline first, then same-target sibling pipelines on the team. Read this before iterating to reuse winning features and avoid repeating discarded approaches.
 * @summary Read prior training-run history
 */
export const AutoresearchTrainingRunsHistoryRetrieveParams = /* @__PURE__ */ zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchTrainingRunsHistoryRetrieveQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Maximum number of prior runs to return (default 5, capped at 20).'),
})

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const AutoresearchRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Soft-delete a pipeline. Stops daily scoring and training. Predictions and metrics are preserved.
 * @summary Archive a pipeline
 */
export const AutoresearchArchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchArchiveCreateBodyNameMax = 255

export const autoresearchArchiveCreateBodyTargetEventMax = 255

export const autoresearchArchiveCreateBodyHorizonDaysMin = -2147483648
export const autoresearchArchiveCreateBodyHorizonDaysMax = 2147483647

export const autoresearchArchiveCreateBodyTrainingLookbackDaysMin = -2147483648
export const autoresearchArchiveCreateBodyTrainingLookbackDaysMax = 2147483647

export const autoresearchArchiveCreateBodyCadenceDaysMin = -2147483648
export const autoresearchArchiveCreateBodyCadenceDaysMax = 2147483647

export const autoresearchArchiveCreateBodyIterationBudgetMin = -2147483648
export const autoresearchArchiveCreateBodyIterationBudgetMax = 2147483647

export const autoresearchArchiveCreateBodyPlateauIterationsMin = -2147483648
export const autoresearchArchiveCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchArchiveCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchArchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchArchiveCreateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchArchiveCreateBodyTargetEventMax)
        .describe("PostHog event name to predict, e.g. '$pageview' or 'signed_up'."),
    target_definition: zod
        .looseObject({})
        .describe('Full target definition including event filters and positive-label conditions.'),
    horizon_days: zod
        .number()
        .min(autoresearchArchiveCreateBodyHorizonDaysMin)
        .max(autoresearchArchiveCreateBodyHorizonDaysMax)
        .optional()
        .describe('Prediction horizon in days. The model predicts whether the target event occurs within this window.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchArchiveCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchArchiveCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples. Larger windows give more data but may include stale behavior.'
        ),
    training_population: zod
        .looseObject({})
        .describe('Population used for training. Defines which users can appear as training examples.'),
    inference_population: zod
        .looseObject({})
        .describe('Population scored daily. Typically broader than the training population.'),
    cadence_days: zod
        .number()
        .min(autoresearchArchiveCreateBodyCadenceDaysMin)
        .max(autoresearchArchiveCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days.'),
    iteration_budget: zod
        .number()
        .min(autoresearchArchiveCreateBodyIterationBudgetMin)
        .max(autoresearchArchiveCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if this score is reached.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchArchiveCreateBodyPlateauIterationsMin)
        .max(autoresearchArchiveCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no AUC improvement is seen in this many consecutive iterations.'),
    output_person_property: zod
        .string()
        .max(autoresearchArchiveCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe("Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'."),
})

/**
 * Pause daily scoring and training. The pipeline can be resumed later.
 * @summary Pause a pipeline
 */
export const AutoresearchPauseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchPauseCreateBodyNameMax = 255

export const autoresearchPauseCreateBodyTargetEventMax = 255

export const autoresearchPauseCreateBodyHorizonDaysMin = -2147483648
export const autoresearchPauseCreateBodyHorizonDaysMax = 2147483647

export const autoresearchPauseCreateBodyTrainingLookbackDaysMin = -2147483648
export const autoresearchPauseCreateBodyTrainingLookbackDaysMax = 2147483647

export const autoresearchPauseCreateBodyCadenceDaysMin = -2147483648
export const autoresearchPauseCreateBodyCadenceDaysMax = 2147483647

export const autoresearchPauseCreateBodyIterationBudgetMin = -2147483648
export const autoresearchPauseCreateBodyIterationBudgetMax = 2147483647

export const autoresearchPauseCreateBodyPlateauIterationsMin = -2147483648
export const autoresearchPauseCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchPauseCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchPauseCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchPauseCreateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchPauseCreateBodyTargetEventMax)
        .describe("PostHog event name to predict, e.g. '$pageview' or 'signed_up'."),
    target_definition: zod
        .looseObject({})
        .describe('Full target definition including event filters and positive-label conditions.'),
    horizon_days: zod
        .number()
        .min(autoresearchPauseCreateBodyHorizonDaysMin)
        .max(autoresearchPauseCreateBodyHorizonDaysMax)
        .optional()
        .describe('Prediction horizon in days. The model predicts whether the target event occurs within this window.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchPauseCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchPauseCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples. Larger windows give more data but may include stale behavior.'
        ),
    training_population: zod
        .looseObject({})
        .describe('Population used for training. Defines which users can appear as training examples.'),
    inference_population: zod
        .looseObject({})
        .describe('Population scored daily. Typically broader than the training population.'),
    cadence_days: zod
        .number()
        .min(autoresearchPauseCreateBodyCadenceDaysMin)
        .max(autoresearchPauseCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days.'),
    iteration_budget: zod
        .number()
        .min(autoresearchPauseCreateBodyIterationBudgetMin)
        .max(autoresearchPauseCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if this score is reached.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchPauseCreateBodyPlateauIterationsMin)
        .max(autoresearchPauseCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no AUC improvement is seen in this many consecutive iterations.'),
    output_person_property: zod
        .string()
        .max(autoresearchPauseCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe("Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'."),
})

/**
 * Resume a paused pipeline. Daily scoring and training will restart on the next cadence tick.
 * @summary Resume a pipeline
 */
export const AutoresearchResumeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchResumeCreateBodyNameMax = 255

export const autoresearchResumeCreateBodyTargetEventMax = 255

export const autoresearchResumeCreateBodyHorizonDaysMin = -2147483648
export const autoresearchResumeCreateBodyHorizonDaysMax = 2147483647

export const autoresearchResumeCreateBodyTrainingLookbackDaysMin = -2147483648
export const autoresearchResumeCreateBodyTrainingLookbackDaysMax = 2147483647

export const autoresearchResumeCreateBodyCadenceDaysMin = -2147483648
export const autoresearchResumeCreateBodyCadenceDaysMax = 2147483647

export const autoresearchResumeCreateBodyIterationBudgetMin = -2147483648
export const autoresearchResumeCreateBodyIterationBudgetMax = 2147483647

export const autoresearchResumeCreateBodyPlateauIterationsMin = -2147483648
export const autoresearchResumeCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchResumeCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchResumeCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchResumeCreateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchResumeCreateBodyTargetEventMax)
        .describe("PostHog event name to predict, e.g. '$pageview' or 'signed_up'."),
    target_definition: zod
        .looseObject({})
        .describe('Full target definition including event filters and positive-label conditions.'),
    horizon_days: zod
        .number()
        .min(autoresearchResumeCreateBodyHorizonDaysMin)
        .max(autoresearchResumeCreateBodyHorizonDaysMax)
        .optional()
        .describe('Prediction horizon in days. The model predicts whether the target event occurs within this window.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchResumeCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchResumeCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples. Larger windows give more data but may include stale behavior.'
        ),
    training_population: zod
        .looseObject({})
        .describe('Population used for training. Defines which users can appear as training examples.'),
    inference_population: zod
        .looseObject({})
        .describe('Population scored daily. Typically broader than the training population.'),
    cadence_days: zod
        .number()
        .min(autoresearchResumeCreateBodyCadenceDaysMin)
        .max(autoresearchResumeCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days.'),
    iteration_budget: zod
        .number()
        .min(autoresearchResumeCreateBodyIterationBudgetMin)
        .max(autoresearchResumeCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if this score is reached.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchResumeCreateBodyPlateauIterationsMin)
        .max(autoresearchResumeCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no AUC improvement is seen in this many consecutive iterations.'),
    output_person_property: zod
        .string()
        .max(autoresearchResumeCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe("Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'."),
})

/**
 * Score the inference population using the champion model and emit autoresearch_prediction events for each scored user. Updates the predicted_p_<target> person property. In production this is triggered by the daily Temporal inference workflow.
 * @summary Run inference (score users)
 */
export const AutoresearchScoreCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Trigger a training run for this pipeline. In production this creates a Task/TaskRun sandbox and starts the autoresearch loop. In the stub implementation it synchronously creates a hand-authored champion recipe and marks the run as completed.
 * @summary Start a training run
 */
export const AutoresearchTrainCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchTrainCreateBodyIterationBudgetMax = 500

export const AutoresearchTrainCreateBody = /* @__PURE__ */ zod.object({
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchTrainCreateBodyIterationBudgetMax)
        .optional()
        .describe('Override the pipeline iteration budget for this training run.'),
})

/**
 * Validate predictions against realized outcomes for all matured prediction dates. A prediction date is matured when today >= prediction_date + horizon_days. Computes realized AUC, Brier score, calibration error (ECE), and lift@10/20 per model. Updates the model's realized_score, calibration_error, and clears the is_preliminary flag. Already-validated dates are skipped. In production this is triggered by the daily Temporal validation workflow after inference runs.
 * @summary Run online validation
 */
export const AutoresearchValidateOnlineCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchValidateOnlineCreateBodyNameMax = 255

export const autoresearchValidateOnlineCreateBodyTargetEventMax = 255

export const autoresearchValidateOnlineCreateBodyHorizonDaysMin = -2147483648
export const autoresearchValidateOnlineCreateBodyHorizonDaysMax = 2147483647

export const autoresearchValidateOnlineCreateBodyTrainingLookbackDaysMin = -2147483648
export const autoresearchValidateOnlineCreateBodyTrainingLookbackDaysMax = 2147483647

export const autoresearchValidateOnlineCreateBodyCadenceDaysMin = -2147483648
export const autoresearchValidateOnlineCreateBodyCadenceDaysMax = 2147483647

export const autoresearchValidateOnlineCreateBodyIterationBudgetMin = -2147483648
export const autoresearchValidateOnlineCreateBodyIterationBudgetMax = 2147483647

export const autoresearchValidateOnlineCreateBodyPlateauIterationsMin = -2147483648
export const autoresearchValidateOnlineCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchValidateOnlineCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchValidateOnlineCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(autoresearchValidateOnlineCreateBodyNameMax).describe('Display name for the pipeline.'),
    description: zod.string().optional().describe('Optional free-text description.'),
    target_event: zod
        .string()
        .max(autoresearchValidateOnlineCreateBodyTargetEventMax)
        .describe("PostHog event name to predict, e.g. '$pageview' or 'signed_up'."),
    target_definition: zod
        .looseObject({})
        .describe('Full target definition including event filters and positive-label conditions.'),
    horizon_days: zod
        .number()
        .min(autoresearchValidateOnlineCreateBodyHorizonDaysMin)
        .max(autoresearchValidateOnlineCreateBodyHorizonDaysMax)
        .optional()
        .describe('Prediction horizon in days. The model predicts whether the target event occurs within this window.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchValidateOnlineCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchValidateOnlineCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples. Larger windows give more data but may include stale behavior.'
        ),
    training_population: zod
        .looseObject({})
        .describe('Population used for training. Defines which users can appear as training examples.'),
    inference_population: zod
        .looseObject({})
        .describe('Population scored daily. Typically broader than the training population.'),
    cadence_days: zod
        .number()
        .min(autoresearchValidateOnlineCreateBodyCadenceDaysMin)
        .max(autoresearchValidateOnlineCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days.'),
    iteration_budget: zod
        .number()
        .min(autoresearchValidateOnlineCreateBodyIterationBudgetMin)
        .max(autoresearchValidateOnlineCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop.'),
    success_auc: zod
        .number()
        .nullish()
        .describe('Target AUC threshold. Training stops early if this score is reached.'),
    plateau_iterations: zod
        .number()
        .min(autoresearchValidateOnlineCreateBodyPlateauIterationsMin)
        .max(autoresearchValidateOnlineCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no AUC improvement is seen in this many consecutive iterations.'),
    output_person_property: zod
        .string()
        .max(autoresearchValidateOnlineCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe("Person property name that stores the daily prediction score, e.g. 'predicted_p_pageview'."),
})

/**
 * Resolve a template key and optional overrides into a concrete pipeline config. For activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'), the target event is auto-resolved from your event schema — check resolved_activity_event and activity_event_alternatives, then override if needed. For 'feature_adoption' and 'repeat_key_behavior', supply target_event. After resolving, call autoresearch-validate-create to check volume and warnings, then autoresearch-create to create the pipeline.
 * @summary Resolve a template
 */
export const AutoresearchResolveTemplateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchResolveTemplateCreateBodyHorizonDaysMax = 365

export const AutoresearchResolveTemplateCreateBody = /* @__PURE__ */ zod.object({
    template_key: zod
        .enum([
            'likely_active_soon',
            'at_risk_of_inactivity',
            'return_after_first_use',
            'feature_adoption',
            'repeat_key_behavior',
        ])
        .describe(
            '* `likely_active_soon` - likely_active_soon\n* `at_risk_of_inactivity` - at_risk_of_inactivity\n* `return_after_first_use` - return_after_first_use\n* `feature_adoption` - feature_adoption\n* `repeat_key_behavior` - repeat_key_behavior'
        )
        .describe(
            'Template to resolve. Use autoresearch-templates-list to see all available templates with descriptions. Required.\n\n* `likely_active_soon` - likely_active_soon\n* `at_risk_of_inactivity` - at_risk_of_inactivity\n* `return_after_first_use` - return_after_first_use\n* `feature_adoption` - feature_adoption\n* `repeat_key_behavior` - repeat_key_behavior'
        ),
    target_event: zod
        .string()
        .optional()
        .describe(
            "Event or action name to use as the prediction target. Required for 'feature_adoption' and 'repeat_key_behavior'. Optional override for activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use') — omit to use the auto-resolved event."
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchResolveTemplateCreateBodyHorizonDaysMax)
        .optional()
        .describe("Override the template's default prediction horizon in days."),
})

/**
 * Return all built-in autoresearch prediction templates. Each entry describes what the template predicts, its default horizon and prediction mode, and whether it requires you to supply a target_event. After choosing a template, call autoresearch-resolve-template-create to get a fully resolved pipeline config ready to pass to autoresearch-create.
 * @summary List available templates
 */
export const AutoresearchTemplatesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AutoresearchTemplatesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Validate a proposed pipeline's target event and population before creating it. Returns volume estimates, base rate, and any warnings. Warnings with severity='error' must be resolved before creation can proceed. Call this before autoresearch-create.
 * @summary Validate a pipeline definition
 */
export const AutoresearchValidateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const autoresearchValidateCreateBodyTargetEventDefault = ``
export const autoresearchValidateCreateBodyHorizonDaysDefault = 7
export const autoresearchValidateCreateBodyHorizonDaysMax = 365

export const autoresearchValidateCreateBodyTrainingLookbackDaysDefault = 180
export const autoresearchValidateCreateBodyTrainingLookbackDaysMin = 7
export const autoresearchValidateCreateBodyTrainingLookbackDaysMax = 730

export const AutoresearchValidateCreateBody = /* @__PURE__ */ zod.object({
    target_event: zod
        .string()
        .default(autoresearchValidateCreateBodyTargetEventDefault)
        .describe(
            "Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .unknown()
        .optional()
        .describe(
            'Optional target definition. Pass {"type": "action", "action_id": N} to predict a PostHog action (multi-step / property / autocapture matcher) instead of a single event.'
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchValidateCreateBodyHorizonDaysMax)
        .default(autoresearchValidateCreateBodyHorizonDaysDefault)
        .describe('Predict whether the target event occurs within this many days.'),
    training_lookback_days: zod
        .number()
        .min(autoresearchValidateCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchValidateCreateBodyTrainingLookbackDaysMax)
        .default(autoresearchValidateCreateBodyTrainingLookbackDaysDefault)
        .describe('How far back to look for training examples. Default: 180.'),
    training_population: zod
        .unknown()
        .optional()
        .describe('Population filter for training examples. Use {} for all identified users.'),
    inference_population: zod
        .unknown()
        .optional()
        .describe('Population filter for daily scoring. Defaults to training_population if not provided.'),
})
