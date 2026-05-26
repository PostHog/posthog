/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 13 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage autoresearch prediction pipelines.

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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
        .describe("PostHog event name to predict, e.g. '$pageview' or 'signed_up'."),
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
    prediction_mode: zod
        .enum(['adoption', 'continuation'])
        .describe('* `adoption` - Adoption\n* `continuation` - Continuation')
        .optional()
        .describe(
            "'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.\n\n* `adoption` - Adoption\n* `continuation` - Continuation"
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

Models are the persisted artifacts produced by training runs. Each model
holds a portable recipe (feature SQL, transforms, model class, params) that
the daily inference workflow compiles to score users.
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

Models are the persisted artifacts produced by training runs. Each model
holds a portable recipe (feature SQL, transforms, model class, params) that
the daily inference workflow compiles to score users.
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
 * List and retrieve training runs for a pipeline.
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
 * Manage autoresearch prediction pipelines.

A pipeline defines a target event, population, and horizon. The autoresearch
training loop finds the best predictive recipe; the inference workflow scores
users daily and emits autoresearch_prediction events.
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
    prediction_mode: zod
        .enum(['adoption', 'continuation'])
        .describe('* `adoption` - Adoption\n* `continuation` - Continuation')
        .optional()
        .describe(
            "'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.\n\n* `adoption` - Adoption\n* `continuation` - Continuation"
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
    prediction_mode: zod
        .enum(['adoption', 'continuation'])
        .describe('* `adoption` - Adoption\n* `continuation` - Continuation')
        .optional()
        .describe(
            "'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.\n\n* `adoption` - Adoption\n* `continuation` - Continuation"
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
    prediction_mode: zod
        .enum(['adoption', 'continuation'])
        .describe('* `adoption` - Adoption\n* `continuation` - Continuation')
        .optional()
        .describe(
            "'adoption': predict first-time occurrence (users who haven't done it yet). 'continuation': predict repeat occurrence.\n\n* `adoption` - Adoption\n* `continuation` - Continuation"
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

export const autoresearchValidateCreateBodyHorizonDaysDefault = 7
export const autoresearchValidateCreateBodyHorizonDaysMax = 365

export const autoresearchValidateCreateBodyPredictionModeDefault = `adoption`

export const AutoresearchValidateCreateBody = /* @__PURE__ */ zod.object({
    target_event: zod
        .string()
        .describe("Event name to predict, e.g. '$pageview'. Must exist in the team's event schema."),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchValidateCreateBodyHorizonDaysMax)
        .default(autoresearchValidateCreateBodyHorizonDaysDefault)
        .describe('Predict whether the target event occurs within this many days.'),
    prediction_mode: zod
        .enum(['adoption', 'continuation'])
        .describe('* `adoption` - adoption\n* `continuation` - continuation')
        .default(autoresearchValidateCreateBodyPredictionModeDefault)
        .describe(
            "'adoption': predict first-time occurrence for users who haven't done it yet. 'continuation': predict repeat occurrence for users who have already done it.\n\n* `adoption` - adoption\n* `continuation` - continuation"
        ),
    training_population: zod
        .unknown()
        .optional()
        .describe('Population filter for training examples. Use {} for all identified users.'),
    inference_population: zod
        .unknown()
        .optional()
        .describe('Population filter for daily scoring. Defaults to training_population if not provided.'),
})
