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

export const experimentHoldoutsListResponseResultsItemNameMax = 400

export const experimentHoldoutsListResponseResultsItemDescriptionMax = 400

export const experimentHoldoutsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const experimentHoldoutsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const experimentHoldoutsListResponseResultsItemCreatedByOneLastNameMax = 150

export const experimentHoldoutsListResponseResultsItemCreatedByOneEmailMax = 254

export const ExperimentHoldoutsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number(),
            name: zod.string().max(experimentHoldoutsListResponseResultsItemNameMax),
            description: zod.string().max(experimentHoldoutsListResponseResultsItemDescriptionMax).nullish(),
            filters: zod.unknown().optional(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(experimentHoldoutsListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(experimentHoldoutsListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(experimentHoldoutsListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(experimentHoldoutsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

export const experimentHoldoutsCreateBodyNameMax = 400

export const experimentHoldoutsCreateBodyDescriptionMax = 400

export const ExperimentHoldoutsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(experimentHoldoutsCreateBodyNameMax),
    description: zod.string().max(experimentHoldoutsCreateBodyDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
})

export const experimentHoldoutsRetrieveResponseNameMax = 400

export const experimentHoldoutsRetrieveResponseDescriptionMax = 400

export const experimentHoldoutsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const experimentHoldoutsRetrieveResponseCreatedByOneFirstNameMax = 150

export const experimentHoldoutsRetrieveResponseCreatedByOneLastNameMax = 150

export const experimentHoldoutsRetrieveResponseCreatedByOneEmailMax = 254

export const ExperimentHoldoutsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    name: zod.string().max(experimentHoldoutsRetrieveResponseNameMax),
    description: zod.string().max(experimentHoldoutsRetrieveResponseDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(experimentHoldoutsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(experimentHoldoutsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(experimentHoldoutsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(experimentHoldoutsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const experimentHoldoutsUpdateBodyNameMax = 400

export const experimentHoldoutsUpdateBodyDescriptionMax = 400

export const ExperimentHoldoutsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(experimentHoldoutsUpdateBodyNameMax),
    description: zod.string().max(experimentHoldoutsUpdateBodyDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
})

export const experimentHoldoutsUpdateResponseNameMax = 400

export const experimentHoldoutsUpdateResponseDescriptionMax = 400

export const experimentHoldoutsUpdateResponseCreatedByOneDistinctIdMax = 200

export const experimentHoldoutsUpdateResponseCreatedByOneFirstNameMax = 150

export const experimentHoldoutsUpdateResponseCreatedByOneLastNameMax = 150

export const experimentHoldoutsUpdateResponseCreatedByOneEmailMax = 254

export const ExperimentHoldoutsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    name: zod.string().max(experimentHoldoutsUpdateResponseNameMax),
    description: zod.string().max(experimentHoldoutsUpdateResponseDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(experimentHoldoutsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(experimentHoldoutsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(experimentHoldoutsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(experimentHoldoutsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const experimentHoldoutsPartialUpdateBodyNameMax = 400

export const experimentHoldoutsPartialUpdateBodyDescriptionMax = 400

export const ExperimentHoldoutsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(experimentHoldoutsPartialUpdateBodyNameMax).optional(),
    description: zod.string().max(experimentHoldoutsPartialUpdateBodyDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
})

export const experimentHoldoutsPartialUpdateResponseNameMax = 400

export const experimentHoldoutsPartialUpdateResponseDescriptionMax = 400

export const experimentHoldoutsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const experimentHoldoutsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const experimentHoldoutsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const experimentHoldoutsPartialUpdateResponseCreatedByOneEmailMax = 254

export const ExperimentHoldoutsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    name: zod.string().max(experimentHoldoutsPartialUpdateResponseNameMax),
    description: zod.string().max(experimentHoldoutsPartialUpdateResponseDescriptionMax).nullish(),
    filters: zod.unknown().optional(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(experimentHoldoutsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(experimentHoldoutsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(experimentHoldoutsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(experimentHoldoutsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

export const experimentSavedMetricsListResponseResultsItemNameMax = 400

export const experimentSavedMetricsListResponseResultsItemDescriptionMax = 400

export const experimentSavedMetricsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const experimentSavedMetricsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const experimentSavedMetricsListResponseResultsItemCreatedByOneLastNameMax = 150

export const experimentSavedMetricsListResponseResultsItemCreatedByOneEmailMax = 254

export const ExperimentSavedMetricsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
                name: zod.string().max(experimentSavedMetricsListResponseResultsItemNameMax),
                description: zod.string().max(experimentSavedMetricsListResponseResultsItemDescriptionMax).nullish(),
                query: zod.unknown(),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(experimentSavedMetricsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(experimentSavedMetricsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(experimentSavedMetricsListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(experimentSavedMetricsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}),
                tags: zod.array(zod.unknown()).optional(),
                user_access_level: zod
                    .string()
                    .nullable()
                    .describe('The effective access level the user has for this object'),
            })
            .describe('Mixin for serializers to add user access control fields')
    ),
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

export const experimentSavedMetricsRetrieveResponseNameMax = 400

export const experimentSavedMetricsRetrieveResponseDescriptionMax = 400

export const experimentSavedMetricsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const experimentSavedMetricsRetrieveResponseCreatedByOneFirstNameMax = 150

export const experimentSavedMetricsRetrieveResponseCreatedByOneLastNameMax = 150

export const experimentSavedMetricsRetrieveResponseCreatedByOneEmailMax = 254

export const ExperimentSavedMetricsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(experimentSavedMetricsRetrieveResponseNameMax),
        description: zod.string().max(experimentSavedMetricsRetrieveResponseDescriptionMax).nullish(),
        query: zod.unknown(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(experimentSavedMetricsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(experimentSavedMetricsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(experimentSavedMetricsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(experimentSavedMetricsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
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

export const experimentSavedMetricsUpdateResponseNameMax = 400

export const experimentSavedMetricsUpdateResponseDescriptionMax = 400

export const experimentSavedMetricsUpdateResponseCreatedByOneDistinctIdMax = 200

export const experimentSavedMetricsUpdateResponseCreatedByOneFirstNameMax = 150

export const experimentSavedMetricsUpdateResponseCreatedByOneLastNameMax = 150

export const experimentSavedMetricsUpdateResponseCreatedByOneEmailMax = 254

export const ExperimentSavedMetricsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(experimentSavedMetricsUpdateResponseNameMax),
        description: zod.string().max(experimentSavedMetricsUpdateResponseDescriptionMax).nullish(),
        query: zod.unknown(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(experimentSavedMetricsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(experimentSavedMetricsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(experimentSavedMetricsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(experimentSavedMetricsUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
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

export const experimentSavedMetricsPartialUpdateResponseNameMax = 400

export const experimentSavedMetricsPartialUpdateResponseDescriptionMax = 400

export const experimentSavedMetricsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const experimentSavedMetricsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const experimentSavedMetricsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const experimentSavedMetricsPartialUpdateResponseCreatedByOneEmailMax = 254

export const ExperimentSavedMetricsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(experimentSavedMetricsPartialUpdateResponseNameMax),
        description: zod.string().max(experimentSavedMetricsPartialUpdateResponseDescriptionMax).nullish(),
        query: zod.unknown(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(experimentSavedMetricsPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(experimentSavedMetricsPartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod.string().max(experimentSavedMetricsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(experimentSavedMetricsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * List experiments for the current project. Supports filtering by status and archival state.
 */
export const ExperimentsListResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.
 */
export const ExperimentsRetrieveResponse = /* @__PURE__ */ zod
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

export const ExperimentsUpdateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.
 */
export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const ExperimentsPartialUpdateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Archive an ended experiment.

Hides the experiment from the default list view. The experiment can be
restored at any time by updating archived=false. Returns 400 if the
experiment is already archived or has not ended yet.
 */
export const ExperimentsArchiveCreateResponse = /* @__PURE__ */ zod
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

export const ExperimentsCopyToProjectCreateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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

export const ExperimentsEndCreateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Launch a draft experiment.

Validates the experiment is in draft state, activates its linked feature flag,
sets start_date to the current server time, and transitions the experiment to running.
Returns 400 if the experiment has already been launched or if the feature flag
configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
 */
export const ExperimentsLaunchCreateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Pause a running experiment.

Deactivates the linked feature flag so it is no longer returned by the
/decide endpoint. Users fall back to the application default (typically
the control experience), and no new exposure events are recorded (i.e.
$feature_flag_called is not fired).
Returns 400 if the experiment is not running or is already paused.
 */
export const ExperimentsPauseCreateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
 * Reset an experiment back to draft state.

Clears start/end dates, conclusion, and archived flag. The feature
flag is left unchanged — users continue to see their assigned variants.

Previously collected events still exist but won't be included in
results unless the start date is manually adjusted after re-launch.

Returns 400 if the experiment is already in draft state.
 */
export const ExperimentsResetCreateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Resume a paused experiment.

Reactivates the linked feature flag so it is returned by /decide again.
Users are re-bucketed deterministically into the same variants they had
before the pause, and exposure tracking resumes.
Returns 400 if the experiment is not running or is not paused.
 */
export const ExperimentsResumeCreateResponse = /* @__PURE__ */ zod
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

export const ExperimentsShipVariantCreateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')
