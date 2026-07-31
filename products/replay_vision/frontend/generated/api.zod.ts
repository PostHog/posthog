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
    AffectedCohortRequestApi,
    ApplyPromptSuggestionRequestApi,
    BulkObserveRequestApi,
    EstimateRequestApi,
    EvaluatePromptSuggestionRequestApi,
    ObserveRequestApi,
    PatchedReplayScannerApi,
    PatchedVisionActionApi,
    ReplayObservationLabelApi,
    ReplayScannerApi,
    SuggestTagsRequestApi,
    VisionActionApi,
} from './api.zod.schemas'

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsCreateBody = VisionActionApi

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsPartialUpdateBody = PatchedVisionActionApi

/**
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires editor access to the scanner.
 */
export const VisionObservationsLabelCreateBody = ReplayObservationLabelApi

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersCreateBody = ReplayScannerApi

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersPartialUpdateBody = PatchedReplayScannerApi

/**
 * Save the users this scanner matched as a static cohort, for surveys, funnels, and retention analysis.
 */
export const VisionScannersAffectedCohortCreateBody = AffectedCohortRequestApi

/**
 * Apply this scanner to many sessions on demand. Starts as many as fit under the in-flight
 * caps and monthly credit quota, reporting the rest as skipped rather than failing the batch.
 */
export const VisionScannersBulkObserveCreateBody = BulkObserveRequestApi

/**
 * Apply this scanner to one specific session, on demand. Returns 202 with the workflow handle.
 */
export const VisionScannersObserveCreateBody = ObserveRequestApi

/**
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires editor access to the scanner.
 */
export const VisionScannersObservationsLabelCreateBody = ReplayObservationLabelApi

/**
 * Apply this suggestion: write a config to the scanner (the prompt plus any type-specific config such as classifier tags or the monitor allow_inconclusive flag), bumping the scanner version, and mark the suggestion applied. Pass `config` to apply an edited subset of the recommendation; omit it to apply the full suggested config. Only the current pending suggestion can be applied. Requires session recording edit access.
 */
export const VisionScannersPromptSuggestionsApplyCreateBody = ApplyPromptSuggestionRequestApi

/**
 * Test this suggestion before applying it: re-run the scanner with the suggested prompt against already-rated sessions in the background and compare each fresh output with the stored one. Results land on the suggestion's `evaluation` field. Poll `current` while status is running. `session_limit` controls how many rated sessions are re-run (thumbs-down prioritized, up to `evaluation_session_cap`). Each successful re-run charges credits like a normal observation of the same model. The request is refused with 402 when the planned credits exceed what is left of the monthly limit. Monitor and classifier scanners get a kept/fixed/regressed classification, while scorer and summarizer scanners show the raw before and after output. Requires session recording edit access.
 */
export const VisionScannersPromptSuggestionsEvaluateCreateBody = EvaluatePromptSuggestionRequestApi

/**
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
export const VisionScannersEstimateCreateBody = EstimateRequestApi

/**
 * Suggest classifier tags grounded in the scanner's own observations and the org's product data.
 */
export const VisionScannersSuggestTagsCreateBody = SuggestTagsRequestApi
