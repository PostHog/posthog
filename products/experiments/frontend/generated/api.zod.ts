/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const experimentHoldoutsCreateBodyNameMax = 400

export const experimentHoldoutsCreateBodyDescriptionMax = 400

export const ExperimentHoldoutsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(experimentHoldoutsCreateBodyNameMax),
    description: zod.string().max(experimentHoldoutsCreateBodyDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
})

export const experimentHoldoutsUpdateBodyNameMax = 400

export const experimentHoldoutsUpdateBodyDescriptionMax = 400

export const ExperimentHoldoutsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(experimentHoldoutsUpdateBodyNameMax),
    description: zod.string().max(experimentHoldoutsUpdateBodyDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
})

export const experimentHoldoutsPartialUpdateBodyNameMax = 400

export const experimentHoldoutsPartialUpdateBodyDescriptionMax = 400

export const ExperimentHoldoutsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(experimentHoldoutsPartialUpdateBodyNameMax).optional(),
    description: zod.string().max(experimentHoldoutsPartialUpdateBodyDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
})

export const experimentSavedMetricsCreateBodyNameMax = 400

export const experimentSavedMetricsCreateBodyDescriptionMax = 400

export const ExperimentSavedMetricsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentSavedMetricsCreateBodyNameMax),
        description: zod.string().max(experimentSavedMetricsCreateBodyDescriptionMax).nullish(),
        query: zod.unknown(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const experimentSavedMetricsUpdateBodyNameMax = 400

export const experimentSavedMetricsUpdateBodyDescriptionMax = 400

export const ExperimentSavedMetricsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentSavedMetricsUpdateBodyNameMax),
        description: zod.string().max(experimentSavedMetricsUpdateBodyDescriptionMax).nullish(),
        query: zod.unknown(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const experimentSavedMetricsPartialUpdateBodyNameMax = 400

export const experimentSavedMetricsPartialUpdateBodyDescriptionMax = 400

export const ExperimentSavedMetricsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentSavedMetricsPartialUpdateBodyNameMax).optional(),
        description: zod.string().max(experimentSavedMetricsPartialUpdateBodyDescriptionMax).nullish(),
        query: zod.unknown().optional(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.
 */
export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsCopyToProjectCreateBody = /* @__PURE__ */ zod.object({
    target_team_id: zod.number().describe('The team ID to copy the experiment to.'),
    feature_flag_key: zod.string().optional().describe('Optional feature flag key to use in the destination team.'),
    name: zod.string().optional().describe('Optional name for the copied experiment.'),
})

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsCreateExposureCohortForExperimentCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsDuplicateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * End a running experiment without shipping a variant.

Sets end_date to now and marks the experiment as stopped. The feature
flag is NOT modified — users continue to see their assigned variants
and exposure events ($feature_flag_called) continue to be recorded.
However, only data up to end_date is included in experiment results.

Use this when:

- You want to freeze the results window without changing which variant
  users see.
- A variant was already shipped manually via the feature flag UI and
  the experiment just needs to be marked complete.

The end_date can be adjusted after ending via PATCH if it needs to be
backdated (e.g. to match when the flag was actually paused).

Other options:
- Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
- Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).

Returns 400 if the experiment is not running.
 */
export const ExperimentsEndCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
        ),
    conclusion_comment: zod.string().nullish().describe('Optional comment about the experiment conclusion.'),
})

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsRecalculateTimeseriesCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Ship a variant to 100% of users and (optionally) end the experiment.

Rewrites the feature flag so that the selected variant is served to everyone.
Existing release conditions (flag groups) are preserved so the change can be
rolled back by deleting the auto-added release condition in the feature flag UI.

Can be called on both running and stopped experiments. If the experiment is
still running, it will also be ended (end_date set and status marked as stopped).
If the experiment has already ended, only the flag is rewritten - this supports
the "end first, ship later" workflow.

If an approval policy requires review before changes on the flag take effect,
the API returns 409 with a change_request_id. The experiment is NOT ended until
the change request is approved and the user retries.

Returns 400 if the experiment is in draft state, the variant_key is not found
on the flag, or the experiment has no linked feature flag.
 */
export const ExperimentsShipVariantCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
        ),
    conclusion_comment: zod.string().nullish().describe('Optional comment about the experiment conclusion.'),
    variant_key: zod.string().describe('The key of the variant to ship to 100% of users.'),
})
