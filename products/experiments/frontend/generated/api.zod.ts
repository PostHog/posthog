/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    ArchiveExperimentApi,
    CopyExperimentToProjectApi,
    CreateFromPromptInputApi,
    EndExperimentApi,
    ExperimentApi,
    ExperimentHoldoutApi,
    ExperimentSavedMetricApi,
    ExperimentSessionContextsRequestApi,
    ExperimentWriteApi,
    PatchedExperimentHoldoutApi,
    PatchedExperimentSavedMetricApi,
    PatchedExperimentWriteApi,
    RecalculateMetricsRequestApi,
    RunningTimeCalculationInputApi,
    ShipVariantApi,
} from './api.zod.schemas'

export const ExperimentHoldoutsCreateBody = ExperimentHoldoutApi

export const ExperimentHoldoutsUpdateBody = ExperimentHoldoutApi

export const ExperimentHoldoutsPartialUpdateBody = PatchedExperimentHoldoutApi

export const ExperimentSavedMetricsCreateBody = ExperimentSavedMetricApi

export const ExperimentSavedMetricsUpdateBody = ExperimentSavedMetricApi

export const ExperimentSavedMetricsPartialUpdateBody = PatchedExperimentSavedMetricApi

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateBody = ExperimentWriteApi

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsUpdateBody = ExperimentWriteApi

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time. Feature-flag config (variants, rollout, payloads) is sent via the feature_flag object.
 */
export const ExperimentsPartialUpdateBody = PatchedExperimentWriteApi

/**
 * Archive an ended experiment.
 *
 * Hides the experiment from the default list view. The experiment can be
 * restored at any time by updating archived=false. When the linked feature
 * flag is still enabled, pass disable_feature_flag=true to also disable and
 * archive it. Returns 400 if the experiment is already archived or has not
 * ended yet.
 */
export const ExperimentsArchiveCreateBody = ArchiveExperimentApi

/**
 * Copy an experiment into another project in the same organization as a new draft.
 */
export const ExperimentsCopyToProjectCreateBody = CopyExperimentToProjectApi

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsCreateExposureCohortForExperimentCreateBody = ExperimentApi

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsDuplicateCreateBody = ExperimentApi

/**
 * End a running experiment without shipping a variant.
 *
 * Sets end_date to now and marks the experiment as stopped. The feature
 * flag is NOT modified — users continue to see their assigned variants
 * and exposure events ($feature_flag_called) continue to be recorded.
 * However, only data up to end_date is included in experiment results.
 *
 * Use this when:
 *
 * - You want to freeze the results window without changing which variant
 *   users see.
 * - A variant was already shipped manually via the feature flag UI and
 *   the experiment just needs to be marked complete.
 *
 * The end_date can be adjusted after ending via PATCH if it needs to be
 * backdated (e.g. to match when the flag was actually paused).
 *
 * Other options:
 * - Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
 * - Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).
 *
 * Returns 400 if the experiment is not running.
 */
export const ExperimentsEndCreateBody = EndExperimentApi

/**
 * Trigger a batch recalculation of all metrics for this experiment.
 *
 * Returns 201 with the new pending recalculation, or 200 with the active one if a recalculation is
 * already pending or in progress for this experiment. The response payload intentionally does not
 * include the `results` array — at POST time the workflow has just been queued and no per-metric
 * results exist yet. Clients should poll `GET metrics_recalculation/{id}/` for results as the workflow
 * progresses.
 */
export const ExperimentsMetricsRecalculationCreateBody = RecalculateMetricsRequestApi

/**
 * Mixin for ViewSets to handle approval-gate exceptions raised from decorated serializers.
 *
 * Intercepts ApprovalRequired (409) and PolicyConflict (400) raised by the @approval_gate
 * decorator on serializer methods and converts them into the same responses the viewset path
 * produces (see decorators._result_to_response), so both paths share one contract.
 */
export const ExperimentsRecalculateTimeseriesCreateBody = ExperimentApi

/**
 * Ship a variant and (optionally) end the experiment.
 *
 * Updates the feature flag so the selected variant gets 100% of the variant
 * distribution. By default, existing release conditions on the flag are preserved
 * untouched — the variant is served only to users who already match them. Pass
 * ``release_to_everyone: true`` to also prepend a catch-all release condition
 * that rolls the variant out to 100% of users (overrides any existing release
 * conditions on the flag).
 *
 * Can be called on both running and stopped experiments. If the experiment is
 * still running, it will also be ended (end_date set and status marked as stopped).
 * If the experiment has already ended, only the flag is rewritten - this supports
 * the "end first, ship later" workflow.
 *
 * If an approval policy requires review before changes on the flag take effect,
 * the API returns 409 with a change_request_id. The experiment is NOT ended until
 * the change request is approved and the user retries.
 *
 * Returns 400 if the experiment is in draft state, the variant_key is not found
 * on the flag, or the experiment has no linked feature flag.
 */
export const ExperimentsShipVariantCreateBody = ShipVariantApi

/**
 * Estimate the recommended sample size and running time for an experiment.
 *
 * Pure statistical calculation — does not read or write any experiment. Pass the metric type, a
 * minimum detectable effect, and either a baseline value or raw baseline statistics. When
 * `exposure_rate_per_day` is provided, the response also includes the estimated running time in days.
 */
export const ExperimentsCalculateRunningTimeCreateBody = RunningTimeCalculationInputApi

/**
 * Create an experiment that compares N versions of an LLM prompt using a metric template.
 *
 * The user picks 2+ versions of an existing LLMPrompt and 1+ metric templates
 * (cost / latency / eval_pass_rate). The endpoint builds the matching variants
 * (control + test-N, each named after its prompt version) and attaches one
 * metric per selected template, each scoped to the prompt's $ai_prompt_name.
 * Resulting experiment is in draft state.
 */
export const ExperimentsCreateFromPromptCreateBody = CreateFromPromptInputApi

/**
 * Resolve experiment context for a batch of session recordings.
 *
 * Batch variant of `session_context`, used to prefetch the replay player's experiments
 * box for a whole recordings list in one request. POST because the id list doesn't fit a
 * query string; the endpoint only reads. Already-computed sessions are served from (and
 * cold ones written to) the same short-lived per-viewer cache the single-session endpoint
 * uses, so opening any prefetched recording renders its context instantly. Sessions whose
 * recording metadata doesn't exist yet are omitted from the response, as are recordings
 * the caller can't access and sessions beyond the batch's recording-day budget (each
 * distinct recording day costs its own set of ClickHouse scans, so only the most recent
 * days are computed per request).
 */
export const ExperimentsSessionContextsCreateBody = ExperimentSessionContextsRequestApi
