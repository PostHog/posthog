/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 23 enabled ops
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
export const AutoresearchListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AutoresearchListQueryParams = () => zod.object({
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
export const AutoresearchCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchCreateBodyNameMax = 255

export const autoresearchCreateBodyTargetEventMax = 255

export const autoresearchCreateBodyHorizonDaysMax = 365

export const autoresearchCreateBodyTrainingLookbackDaysMin = 7
export const autoresearchCreateBodyTrainingLookbackDaysMax = 730

export const autoresearchCreateBodyCadenceDaysMax = 365

export const autoresearchCreateBodyIterationBudgetMax = 500

export const autoresearchCreateBodySuccessAucMin = 0
export const autoresearchCreateBodySuccessAucMax = 1

export const autoresearchCreateBodyPlateauIterationsMax = 2147483647

export const autoresearchCreateBodyOutputPersonPropertyMax = 255

export const AutoresearchCreateBody = () => zod.object({
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
        .union([
            zod
                .object({
                    type: zod.enum(['event']),
                })
                .describe('Predict target_event. The default when target_definition is omitted.'),
            zod
                .object({
                    type: zod.enum(['action']),
                    action_id: zod.number().min(1).describe('ID of the action to predict.'),
                })
                .describe('Predict a PostHog action in this project.'),
        ])
        .optional()
        .describe(
            'Omit (or pass {\"type\": \"event\"}) to predict target_event; pass {\"type\": \"action\", \"action_id\": N} to predict a PostHog action. No other shapes are accepted.'
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyHorizonDaysMax)
        .optional()
        .describe(
            'Prediction horizon in days (1-365). The model predicts whether the target event occurs within this window.'
        ),
    training_lookback_days: zod
        .number()
        .min(autoresearchCreateBodyTrainingLookbackDaysMin)
        .max(autoresearchCreateBodyTrainingLookbackDaysMax)
        .optional()
        .describe(
            'How far back to look for training examples (7-730 days). Larger windows give more data but may include stale behavior. Default: 180.'
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
        .min(1)
        .max(autoresearchCreateBodyCadenceDaysMax)
        .optional()
        .describe('Re-score the inference population every N days (1-365). Default: 1.'),
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyIterationBudgetMax)
        .optional()
        .describe('Total training iterations allowed for the autoresearch loop (1-500). Default: 50.'),
    success_auc: zod
        .number()
        .min(autoresearchCreateBodySuccessAucMin)
        .max(autoresearchCreateBodySuccessAucMax)
        .nullish()
        .describe('Target AUC threshold (0-1). Training stops early if reached. Default: 0.75.'),
    plateau_iterations: zod
        .number()
        .min(1)
        .max(autoresearchCreateBodyPlateauIterationsMax)
        .optional()
        .describe('Stop training if no improvement in this many consecutive iterations (at least 1). Default: 10.'),
    output_person_property: zod
        .string()
        .max(autoresearchCreateBodyOutputPersonPropertyMax)
        .optional()
        .describe(
            "Person property name for the prediction score, e.g. 'predicted_p_pageview'. Auto-derived from target_event if omitted. Letters, digits, and _ $ . - only, and it cannot start with $ (reserved for PostHog's own properties); must be unique among this project's non-archived pipelines."
        ),
})

/**
 * List and retrieve champion/challenger models for a pipeline.
 *
 * Models are the persisted artifacts produced by training runs. Each model
 * holds a portable recipe (feature SQL, transforms, model class, params) that
 * the daily inference workflow compiles to score users.
 */
export const AutoresearchModelsListParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AutoresearchModelsListQueryParams = () => zod.object({
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
export const AutoresearchModelsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch model.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * List and retrieve inference and validation runs for a pipeline.
 */
export const AutoresearchRunsListParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AutoresearchRunsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * List steering suggestions for a pipeline, ordered most recent first. Check 'status' to see which have been picked up or acted on by the agent.
 * @summary List suggestions
 */
export const AutoresearchSuggestionsListParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AutoresearchSuggestionsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Inject a free-text hypothesis or direction into a running pipeline. The sandbox agent reads queued suggestions at the start of each iteration batch and decides: translate into a concrete iteration ('acted_on'), apply as a search constraint ('picked_up'), or reject with rationale ('dismissed'). Use priority='try_next' to instruct the agent to act on this before autonomous iterations; 'consider' is advisory. Check 'agent_response' after the next training run to see how the suggestion was interpreted.
 * @summary Submit a suggestion
 */
export const AutoresearchSuggestionsCreateParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchSuggestionsCreateBodyPromptMax = 2000

export const autoresearchSuggestionsCreateBodyPriorityDefault = `consider`

export const AutoresearchSuggestionsCreateBody = () => zod.object({
    prompt: zod
        .string()
        .max(autoresearchSuggestionsCreateBodyPromptMax)
        .describe(
            "Free-text hypothesis or direction for the agent to explore, e.g. 'try a tree-based model' or 'remove recency features, I suspect leakage'."
        ),
    priority: zod
        .enum(['try_next', 'consider'])
        .describe('\* `try_next` - try_next\n\* `consider` - consider')
        .default(autoresearchSuggestionsCreateBodyPriorityDefault)
        .describe(
            "'try_next' asks the agent to act on this before other autonomous iterations; 'consider' is advisory context.\n\n\* `try_next` - try_next\n\* `consider` - consider"
        ),
})

/**
 * Record how the agent handled a steering suggestion: set status to 'picked_up' (applied as a search constraint), 'acted_on' (spawned iterations), or 'dismissed' (rejected — explain in agent_response), and write the agent_response note the human will read. Call this from the training loop after deciding what to do with a pending suggestion. Recording an iteration with parent_suggestion set already advances a suggestion to 'acted_on'; use this to add the narrative or to mark a suggestion picked_up/dismissed without spawning an iteration. A suggestion only moves forward (queued, picked_up, then acted_on or dismissed); the same status again updates the note.
 * @summary Respond to a suggestion
 */
export const AutoresearchSuggestionsRespondCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch suggestion.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchSuggestionsRespondCreateBodyAgentResponseMax = 2000

export const AutoresearchSuggestionsRespondCreateBody = () => zod
    .object({
        status: zod
            .enum(['picked_up', 'acted_on', 'dismissed'])
            .describe('\* `picked_up` - picked_up\n\* `acted_on` - acted_on\n\* `dismissed` - dismissed')
            .describe(
                "How the agent handled the suggestion: 'picked_up' (applied as a search constraint), 'acted_on' (spawned one or more iterations), or 'dismissed' (rejected — explain why in agent_response).\n\n\* `picked_up` - picked_up\n\* `acted_on` - acted_on\n\* `dismissed` - dismissed"
            ),
        agent_response: zod
            .string()
            .max(autoresearchSuggestionsRespondCreateBodyAgentResponseMax)
            .optional()
            .describe(
                'Plain-English note on how the suggestion was interpreted and acted upon. A dismissal needs a note, sent now or recorded earlier. Omit it to keep the note already recorded; send an empty string to clear it.'
            ),
    })
    .describe('Input for the agent to record how it interpreted a steering suggestion.')

/**
 * List and retrieve training runs for a pipeline.
 *
 * A training run records the agent's search for a model: each iteration's recipe and holdout
 * score, and the summary of the run once it completes.
 */
export const AutoresearchTrainingRunsListParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AutoresearchTrainingRunsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Open a new training run for a pipeline and return its id. An agent — the in-house sandbox, an external bring-your-own agent, or a scheduled job — then records iterations against this run and finalizes it with the complete endpoint. The run starts in 'running'.
 * @summary Open a training run
 */
export const AutoresearchTrainingRunsCreateParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainingRunsCreateBodyIterationBudgetMax = 500

export const AutoresearchTrainingRunsCreateBody = () => zod
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
export const AutoresearchTrainingRunsArtifactsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Fetch one file from this training run's artifact bundle, base64-encoded.
 * @summary Get an artifact bundle file
 */
export const AutoresearchTrainingRunsArtifactsGetCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainingRunsArtifactsGetCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsGetCreateBody = () => zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsGetCreateBodyPathMax)
            .describe("Relative path of the file within the bundle, e.g. 'train.py'."),
    })
    .describe('Input for fetching or deleting one bundle file by path.')

/**
 * Upload one file of this training run's artifact bundle. Send the file contents base64-encoded in content_base64. Re-uploading the same path overwrites it. Use this — not curl/set_output — to author train.py, predict.py, and features.sql. The bundle is frozen once the run completes or fails.
 * @summary Upload an artifact bundle file
 */
export const AutoresearchTrainingRunsArtifactsUploadCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainingRunsArtifactsUploadCreateBodyPathMax = 500

export const AutoresearchTrainingRunsArtifactsUploadCreateBody = () => zod
    .object({
        path: zod
            .string()
            .max(autoresearchTrainingRunsArtifactsUploadCreateBodyPathMax)
            .describe(
                "Relative path within the bundle, e.g. 'train.py', 'predict.py', 'features.sql', or 'eda\/iter-3-gbm.ipynb'. Segments are limited to [A-Za-z0-9_.-]; absolute paths and '..' traversal are rejected."
            ),
        content_base64: zod
            .string()
            .describe(
                'File contents, base64-encoded. Decoded server-side and written to object storage. Max 10 MB decoded.'
            ),
    })
    .describe("Input for uploading one file of a training run's artifact bundle.")

/**
 * Finalize a training run. The backend selects the kept iteration with the highest holdout score, decides champion vs challenger via the promotion ladder, and persists the model. best_iteration_id is advisory: it breaks a tie at the top score and is otherwise logged and ignored. Agents cannot set the champion directly, because promotion is server-side.
 * @summary Complete a training run
 */
export const AutoresearchTrainingRunsCompleteCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneTopFeaturesItemNameMax = 200

export const autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneTopFeaturesItemImportanceMin = 0

export const autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneTopFeaturesMax = 30

export const autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneMethodMax = 500

export const autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneNoteMax = 500

export const autoresearchTrainingRunsCompleteCreateBodyRecommendedNextDefault = ``
export const autoresearchTrainingRunsCompleteCreateBodyRecommendedNextMax = 2000

export const autoresearchTrainingRunsCompleteCreateBodyDistillationDefault = ``
export const autoresearchTrainingRunsCompleteCreateBodyDistillationMax = 2000

export const autoresearchTrainingRunsCompleteCreateBodyReportNotebookShortIdDefault = ``

export const AutoresearchTrainingRunsCompleteCreateBody = () => zod
    .object({
        best_iteration_id: zod
            .string()
            .nullish()
            .describe(
                'Advisory nomination. The server promotes the kept iteration with the highest holdout_score; this id only breaks a tie at that score, and a lower-scoring nomination is logged and ignored.'
            ),
        model_explanation: zod
            .object({
                top_features: zod
                    .array(
                        zod.object({
                            name: zod
                                .string()
                                .max(
                                    autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneTopFeaturesItemNameMax
                                )
                                .describe('Feature column name, as returned by the feature SQL.'),
                            importance: zod
                                .number()
                                .min(
                                    autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneTopFeaturesItemImportanceMin
                                )
                                .describe(
                                    'Non-negative importance, for example the mean holdout AUC drop when the feature is shuffled.'
                                ),
                            direction: zod
                                .enum(['positive', 'negative'])
                                .describe('\* `positive` - Positive\n\* `negative` - Negative')
                                .describe(
                                    "'positive' if a higher value raises the predicted probability, 'negative' if it lowers it.\n\n\* `positive` - Positive\n\* `negative` - Negative"
                                ),
                        })
                    )
                    .max(autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneTopFeaturesMax)
                    .optional()
                    .describe('At most 30 features, strongest first.'),
                method: zod
                    .string()
                    .max(autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneMethodMax)
                    .optional()
                    .describe(
                        "Short description of how the importances were computed, e.g. 'permutation importance on holdout'."
                    ),
                note: zod
                    .string()
                    .max(autoresearchTrainingRunsCompleteCreateBodyModelExplanationOneNoteMax)
                    .optional()
                    .describe('Optional caveat shown under the chart.'),
            })
            .describe('Global feature importances for the model card.')
            .optional()
            .describe('Global feature importance \/ directionality bundle for the champion model card.'),
        recommended_next: zod
            .string()
            .max(autoresearchTrainingRunsCompleteCreateBodyRecommendedNextMax)
            .default(autoresearchTrainingRunsCompleteCreateBodyRecommendedNextDefault)
            .describe(
                'What a future run should try next, given what this run learned. Stored in the run summary so the next run reads it during orientation. Keep it short and concrete; max 2000 characters.'
            ),
        distillation: zod
            .string()
            .max(autoresearchTrainingRunsCompleteCreateBodyDistillationMax)
            .default(autoresearchTrainingRunsCompleteCreateBodyDistillationDefault)
            .describe(
                'A 1–2 sentence distillation of what this run learned — the winning signal, the key transform, the dead-ends. Stored in the run summary as the cheapest thing the next run reads. Max 2000 characters.'
            ),
        report_notebook_short_id: zod
            .string()
            .default(autoresearchTrainingRunsCompleteCreateBodyReportNotebookShortIdDefault)
            .describe(
                'Short id of the report notebook you built for this run. Stored in the run summary only if the notebook exists in this project; an unknown id is dropped and does not fail the completion.'
            ),
    })
    .describe('Input for finalizing a training run. The backend selects\/promotes the champion.')

/**
 * Record one iteration of an open training run. Idempotent on iteration_number: re-sending the same number updates that iteration. A new iteration_number is refused once the run's iteration_budget is used. The recipe is validated server-side: feature_sql must be a read-only SELECT from {anchors} keyed on person_id, and model_class must be set. The class allowlist applies only at completion, to a run that uploaded no bundle.
 * @summary Record a training iteration
 */
export const AutoresearchTrainingRunsIterationsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyIterationNumberMax = 2147483647

export const autoresearchTrainingRunsIterationsCreateBodyTrainScoreMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyTrainScoreMax = 1

export const autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMax = 1

export const autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault = ``
export const autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionMax = 2000

export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin = 0
export const autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax = 1

export const AutoresearchTrainingRunsIterationsCreateBody = () => zod
    .object({
        iteration_number: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyIterationNumberMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyIterationNumberMax)
            .describe(
                'Zero-based index of this iteration within the run. Re-sending the same number updates that iteration (idempotent).'
            ),
        recipe_snapshot: zod
            .object({
                feature_sql: zod
                    .string()
                    .describe('A read-only HogQL SELECT from {anchors}, one row per person, keyed on person_id.'),
                feature_transforms: zod
                    .array(zod.looseObject({}))
                    .nullish()
                    .describe(
                        'Transforms the bundle applies to the feature columns; null or absent means none, and the in-process path accepts none.'
                    ),
            })
            .describe(
                'Compact recipe for this iteration: feature_sql (HogQL SELECT keyed on person_id) and transforms.'
            ),
        model_spec: zod
            .object({
                model_class: zod.string().describe('Dotted path of the estimator class.'),
                model_params: zod
                    .record(zod.string(), zod.unknown())
                    .nullish()
                    .describe("Keyword arguments for the estimator's constructor; null or absent means the defaults."),
            })
            .describe(
                'model_class and model_params tried this iteration. Any class is accepted here; the sklearn\/xgboost allowlist applies at completion, to a run that uploaded no bundle.'
            ),
        status: zod
            .enum(['kept', 'discarded', 'crashed'])
            .describe('\* `kept` - kept\n\* `discarded` - discarded\n\* `crashed` - crashed')
            .describe(
                "'kept' if this iteration improved on the best score, 'discarded' otherwise, 'crashed' on failure.\n\n\* `kept` - kept\n\* `discarded` - discarded\n\* `crashed` - crashed"
            ),
        train_score: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyTrainScoreMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyTrainScoreMax)
            .nullish()
            .describe('Training-set AUC for this iteration (0-1).'),
        holdout_score: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyHoldoutScoreMax)
            .nullish()
            .describe('Held-out AUC for this iteration (0-1). Used to pick the champion at completion.'),
        agent_description: zod
            .string()
            .max(autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionMax)
            .default(autoresearchTrainingRunsIterationsCreateBodyAgentDescriptionDefault)
            .describe("Agent's plain-English rationale for this iteration. Max 2000 characters."),
        agent_confidence: zod
            .number()
            .min(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMin)
            .max(autoresearchTrainingRunsIterationsCreateBodyAgentConfidenceMax)
            .nullish()
            .describe("Agent's self-assessed confidence (0-1) that this iteration helps."),
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
export const AutoresearchTrainingRunsMaterializeFeaturesCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch training run.'),
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AutoresearchTrainingRunsMaterializeFeaturesCreateBody = () => zod
    .object({
        features_sql: zod
            .string()
            .describe(
                'Your HogQL feature query, using the {anchors}\/{lookback_days} contract. Must be a read-only SELECT keyed on person_id (aliased to distinct_id), one row per user. The backend runs it server-side against the labeled training population — no 500-row cap — and writes the resulting train\/holdout feature and label parquet files into your sandbox.'
            ),
    })
    .describe("Input for materializing the labeled training feature matrix into the run's sandbox.")

/**
 * Return recent completed training runs and their iteration trails so a new run can learn from what was already tried. Scoped to this pipeline first, then same-target sibling pipelines on the team. Read this before iterating to reuse winning features and avoid repeating discarded approaches.
 * @summary Read prior training-run history
 */
export const AutoresearchTrainingRunsHistoryRetrieveParams = () => zod.object({
    pipeline_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainingRunsHistoryRetrieveQueryLimitDefault = 5
export const autoresearchTrainingRunsHistoryRetrieveQueryLimitMax = 20

export const AutoresearchTrainingRunsHistoryRetrieveQueryParams = () => zod.object({
    limit: zod
        .number()
        .min(1)
        .max(autoresearchTrainingRunsHistoryRetrieveQueryLimitMax)
        .default(autoresearchTrainingRunsHistoryRetrieveQueryLimitDefault)
        .describe('Maximum number of prior runs to return (default 5, at most 20).'),
})

/**
 * Manage autoresearch prediction pipelines.
 *
 * A pipeline defines a target event, population, and horizon. The autoresearch
 * training loop finds the best predictive recipe; the inference workflow scores
 * users daily and emits autoresearch_prediction events.
 */
export const AutoresearchRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Return the realized metrics online validation recorded for each model on each validated prediction date, newest date first. Each row has realized AUC with a 95% interval, Brier score, calibration error, quantile calibration bins, mean predicted probability against the base rate, lift, and the model's role when it emitted and now. The rows come from the validation runs, so a former champion that a promotion archived keeps its history. Read-only; it runs no queries.
 * @summary Read realized performance history
 */
export const AutoresearchOnlinePerformanceRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchOnlinePerformanceRetrieveQueryLimitDefault = 60
export const autoresearchOnlinePerformanceRetrieveQueryLimitMax = 180

export const AutoresearchOnlinePerformanceRetrieveQueryParams = () => zod.object({
    limit: zod
        .number()
        .min(1)
        .max(autoresearchOnlinePerformanceRetrieveQueryLimitMax)
        .default(autoresearchOnlinePerformanceRetrieveQueryLimitDefault)
        .describe(
            'Maximum number of validated prediction dates to return, newest first (default 60, at most 180). Each date returns one row per model that emitted predictions on it.'
        ),
})

/**
 * Start scoring the inference population using the champion model. Scoring runs in the background: it emits autoresearch_prediction events for each scored user and sets the pipeline's output_person_property on each scored person. The response returns at once with the running run. A second request while a run is running returns that run and starts nothing. The daily Temporal inference workflow also scores each pipeline on its cadence.
 * @summary Run inference (score users)
 */
export const AutoresearchScoreCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Start an asynchronous training run for this pipeline. Creates a Task/TaskRun sandbox where the autoresearch agent iterates on features and models, and returns the run immediately with status 'running'. Poll the training run until it reaches a terminal status (completed or failed). A pipeline's first run has no champion until it completes and promotion runs; on a retrain the existing champion stays live and keeps scoring until a new one is promoted.
 * @summary Start a training run
 */
export const AutoresearchTrainCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this autoresearch pipeline.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchTrainCreateBodyIterationBudgetMax = 500

export const AutoresearchTrainCreateBody = () => zod.object({
    iteration_budget: zod
        .number()
        .min(1)
        .max(autoresearchTrainCreateBodyIterationBudgetMax)
        .optional()
        .describe('Override the pipeline iteration budget for this training run.'),
})

/**
 * Resolve a template key and optional overrides into a concrete pipeline config. For activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'), the target event is auto-resolved from your event schema — check resolved_activity_event and activity_event_alternatives, then override if needed. For 'feature_adoption' and 'repeat_key_behavior', supply target_event. After resolving, call autoresearch-validate-create to check volume and warnings, then autoresearch-create to create the pipeline.
 * @summary Resolve a template
 */
export const AutoresearchResolveTemplateCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchResolveTemplateCreateBodyHorizonDaysMax = 365

export const AutoresearchResolveTemplateCreateBody = () => zod.object({
    template_key: zod
        .enum([
            'likely_active_soon',
            'at_risk_of_inactivity',
            'return_after_first_use',
            'feature_adoption',
            'repeat_key_behavior',
        ])
        .describe(
            '\* `likely_active_soon` - Likely Active Soon\n\* `at_risk_of_inactivity` - At Risk Of Inactivity\n\* `return_after_first_use` - Return After First Use\n\* `feature_adoption` - Feature Adoption\n\* `repeat_key_behavior` - Repeat Key Behavior'
        )
        .describe(
            'Template to resolve. The templates endpoint lists each one with its description. Required.\n\n\* `likely_active_soon` - Likely Active Soon\n\* `at_risk_of_inactivity` - At Risk Of Inactivity\n\* `return_after_first_use` - Return After First Use\n\* `feature_adoption` - Feature Adoption\n\* `repeat_key_behavior` - Repeat Key Behavior'
        ),
    target_event: zod
        .string()
        .optional()
        .describe(
            "Event name to use as the prediction target. Required for 'feature_adoption' and 'repeat_key_behavior'. Optional override for activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', 'return_after_first_use'); omit to use the auto-resolved event. To predict an action, create the pipeline with target_definition after resolving."
        ),
    horizon_days: zod
        .number()
        .min(1)
        .max(autoresearchResolveTemplateCreateBodyHorizonDaysMax)
        .optional()
        .describe("Override the template's default prediction horizon in days."),
})

/**
 * Validate a proposed pipeline's target event and population before creating it. Returns volume estimates, base rate, and any warnings. Creation does not enforce the result: 'horizon_exceeds_lookback' and an 'error' 'population_too_large' mean a run would fail, and the other 'error' codes mean the data is too thin for a reliable model. Call this before autoresearch-create.
 * @summary Validate a pipeline definition
 */
export const AutoresearchValidateCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const autoresearchValidateCreateBodyTargetEventDefault = ``
export const autoresearchValidateCreateBodyHorizonDaysDefault = 7
export const autoresearchValidateCreateBodyHorizonDaysMax = 365

export const autoresearchValidateCreateBodyTrainingLookbackDaysDefault = 180
export const autoresearchValidateCreateBodyTrainingLookbackDaysMin = 7
export const autoresearchValidateCreateBodyTrainingLookbackDaysMax = 730

export const AutoresearchValidateCreateBody = () => zod.object({
    target_event: zod
        .string()
        .default(autoresearchValidateCreateBodyTargetEventDefault)
        .describe(
            "Event name to predict, e.g. '$pageview'. Must exist in the team's event schema. Omit when predicting an action target (pass target_definition instead)."
        ),
    target_definition: zod
        .union([
            zod
                .object({
                    type: zod.enum(['event']),
                })
                .describe('Predict target_event. The default when target_definition is omitted.'),
            zod
                .object({
                    type: zod.enum(['action']),
                    action_id: zod.number().min(1).describe('ID of the action to predict.'),
                })
                .describe('Predict a PostHog action in this project.'),
        ])
        .optional()
        .describe(
            'Optional target definition. Pass {\"type\": \"action\", \"action_id\": N} to predict a PostHog action (multi-step \/ property \/ autocapture matcher) instead of a single event.'
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
        .looseObject({})
        .optional()
        .describe('Population filter for training examples. Use {} for all identified users.'),
    inference_population: zod
        .looseObject({})
        .optional()
        .describe(
            'Population filter for daily scoring. When omitted or empty, the training population is counted, as creation stores it.'
        ),
})
