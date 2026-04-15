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

export const earlyAccessFeatureListResponseResultsItemFeatureFlagOneKeyMax = 400

export const earlyAccessFeatureListResponseResultsItemFeatureFlagOneVersionMin = -2147483648
export const earlyAccessFeatureListResponseResultsItemFeatureFlagOneVersionMax = 2147483647

export const earlyAccessFeatureListResponseResultsItemNameMax = 200

export const earlyAccessFeatureListResponseResultsItemDocumentationUrlMax = 800

export const EarlyAccessFeatureListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            feature_flag: zod.object({
                id: zod.number(),
                team_id: zod.number(),
                name: zod.string().optional(),
                key: zod.string().max(earlyAccessFeatureListResponseResultsItemFeatureFlagOneKeyMax),
                filters: zod.record(zod.string(), zod.unknown()).optional(),
                deleted: zod.boolean().optional(),
                active: zod.boolean().optional(),
                ensure_experience_continuity: zod.boolean().nullish(),
                has_encrypted_payloads: zod.boolean().nullish(),
                version: zod
                    .number()
                    .min(earlyAccessFeatureListResponseResultsItemFeatureFlagOneVersionMin)
                    .max(earlyAccessFeatureListResponseResultsItemFeatureFlagOneVersionMax)
                    .nullish(),
                evaluation_runtime: zod
                    .union([
                        zod
                            .enum(['server', 'client', 'all'])
                            .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                    ),
                bucketing_identifier: zod
                    .union([
                        zod
                            .enum(['distinct_id', 'device_id'])
                            .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                    ),
                evaluation_contexts: zod.array(zod.string()),
            }),
            name: zod
                .string()
                .max(earlyAccessFeatureListResponseResultsItemNameMax)
                .describe('The name of the early access feature.'),
            description: zod
                .string()
                .optional()
                .describe(
                    'A longer description of what this early access feature does, shown to users in the opt-in UI.'
                ),
            stage: zod
                .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
                .describe(
                    '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
                )
                .describe(
                    'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
                ),
            documentation_url: zod
                .url()
                .max(earlyAccessFeatureListResponseResultsItemDocumentationUrlMax)
                .optional()
                .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
            payload: zod
                .record(zod.string(), zod.unknown())
                .describe('Feature flag payload for this early access feature'),
            created_at: zod.iso.datetime({}),
        })
    ),
})

export const earlyAccessFeatureCreateBodyNameMax = 200

export const earlyAccessFeatureCreateBodyDocumentationUrlMax = 800

export const EarlyAccessFeatureCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(earlyAccessFeatureCreateBodyNameMax).describe('The name of the early access feature.'),
    description: zod
        .string()
        .optional()
        .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
    stage: zod
        .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
        .describe(
            '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        )
        .describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        ),
    documentation_url: zod
        .url()
        .max(earlyAccessFeatureCreateBodyDocumentationUrlMax)
        .optional()
        .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
    payload: zod.unknown().optional().describe('Arbitrary JSON metadata associated with this feature.'),
    feature_flag_id: zod
        .number()
        .optional()
        .describe(
            'Optional ID of an existing feature flag to link. If omitted, a new flag is auto-created from the feature name. The flag must not already be linked to another feature, must not be group-based, and must not be multivariate.'
        ),
    _create_in_folder: zod.string().optional(),
})

export const earlyAccessFeatureRetrieveResponseFeatureFlagOneKeyMax = 400

export const earlyAccessFeatureRetrieveResponseFeatureFlagOneVersionMin = -2147483648
export const earlyAccessFeatureRetrieveResponseFeatureFlagOneVersionMax = 2147483647

export const earlyAccessFeatureRetrieveResponseNameMax = 200

export const earlyAccessFeatureRetrieveResponseDocumentationUrlMax = 800

export const EarlyAccessFeatureRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    feature_flag: zod.object({
        id: zod.number(),
        team_id: zod.number(),
        name: zod.string().optional(),
        key: zod.string().max(earlyAccessFeatureRetrieveResponseFeatureFlagOneKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        version: zod
            .number()
            .min(earlyAccessFeatureRetrieveResponseFeatureFlagOneVersionMin)
            .max(earlyAccessFeatureRetrieveResponseFeatureFlagOneVersionMax)
            .nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        evaluation_contexts: zod.array(zod.string()),
    }),
    name: zod.string().max(earlyAccessFeatureRetrieveResponseNameMax).describe('The name of the early access feature.'),
    description: zod
        .string()
        .optional()
        .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
    stage: zod
        .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
        .describe(
            '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        )
        .describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        ),
    documentation_url: zod
        .url()
        .max(earlyAccessFeatureRetrieveResponseDocumentationUrlMax)
        .optional()
        .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
    payload: zod.record(zod.string(), zod.unknown()).describe('Feature flag payload for this early access feature'),
    created_at: zod.iso.datetime({}),
})

export const earlyAccessFeatureUpdateBodyNameMax = 200

export const earlyAccessFeatureUpdateBodyDocumentationUrlMax = 800

export const EarlyAccessFeatureUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(earlyAccessFeatureUpdateBodyNameMax).describe('The name of the early access feature.'),
    description: zod
        .string()
        .optional()
        .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
    stage: zod
        .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
        .describe(
            '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        )
        .describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        ),
    documentation_url: zod
        .url()
        .max(earlyAccessFeatureUpdateBodyDocumentationUrlMax)
        .optional()
        .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
})

export const earlyAccessFeatureUpdateResponseFeatureFlagOneKeyMax = 400

export const earlyAccessFeatureUpdateResponseFeatureFlagOneVersionMin = -2147483648
export const earlyAccessFeatureUpdateResponseFeatureFlagOneVersionMax = 2147483647

export const earlyAccessFeatureUpdateResponseNameMax = 200

export const earlyAccessFeatureUpdateResponseDocumentationUrlMax = 800

export const EarlyAccessFeatureUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    feature_flag: zod.object({
        id: zod.number(),
        team_id: zod.number(),
        name: zod.string().optional(),
        key: zod.string().max(earlyAccessFeatureUpdateResponseFeatureFlagOneKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        version: zod
            .number()
            .min(earlyAccessFeatureUpdateResponseFeatureFlagOneVersionMin)
            .max(earlyAccessFeatureUpdateResponseFeatureFlagOneVersionMax)
            .nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        evaluation_contexts: zod.array(zod.string()),
    }),
    name: zod.string().max(earlyAccessFeatureUpdateResponseNameMax).describe('The name of the early access feature.'),
    description: zod
        .string()
        .optional()
        .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
    stage: zod
        .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
        .describe(
            '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        )
        .describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        ),
    documentation_url: zod
        .url()
        .max(earlyAccessFeatureUpdateResponseDocumentationUrlMax)
        .optional()
        .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
    payload: zod.record(zod.string(), zod.unknown()).describe('Feature flag payload for this early access feature'),
    created_at: zod.iso.datetime({}),
})

export const earlyAccessFeaturePartialUpdateBodyNameMax = 200

export const earlyAccessFeaturePartialUpdateBodyDocumentationUrlMax = 800

export const EarlyAccessFeaturePartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(earlyAccessFeaturePartialUpdateBodyNameMax)
        .optional()
        .describe('The name of the early access feature.'),
    description: zod
        .string()
        .optional()
        .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
    stage: zod
        .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
        .describe(
            '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        )
        .optional()
        .describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        ),
    documentation_url: zod
        .url()
        .max(earlyAccessFeaturePartialUpdateBodyDocumentationUrlMax)
        .optional()
        .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
})

export const earlyAccessFeaturePartialUpdateResponseFeatureFlagOneKeyMax = 400

export const earlyAccessFeaturePartialUpdateResponseFeatureFlagOneVersionMin = -2147483648
export const earlyAccessFeaturePartialUpdateResponseFeatureFlagOneVersionMax = 2147483647

export const earlyAccessFeaturePartialUpdateResponseNameMax = 200

export const earlyAccessFeaturePartialUpdateResponseDocumentationUrlMax = 800

export const EarlyAccessFeaturePartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    feature_flag: zod.object({
        id: zod.number(),
        team_id: zod.number(),
        name: zod.string().optional(),
        key: zod.string().max(earlyAccessFeaturePartialUpdateResponseFeatureFlagOneKeyMax),
        filters: zod.record(zod.string(), zod.unknown()).optional(),
        deleted: zod.boolean().optional(),
        active: zod.boolean().optional(),
        ensure_experience_continuity: zod.boolean().nullish(),
        has_encrypted_payloads: zod.boolean().nullish(),
        version: zod
            .number()
            .min(earlyAccessFeaturePartialUpdateResponseFeatureFlagOneVersionMin)
            .max(earlyAccessFeaturePartialUpdateResponseFeatureFlagOneVersionMax)
            .nullish(),
        evaluation_runtime: zod
            .union([
                zod
                    .enum(['server', 'client', 'all'])
                    .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
            ),
        bucketing_identifier: zod
            .union([
                zod
                    .enum(['distinct_id', 'device_id'])
                    .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
            ),
        evaluation_contexts: zod.array(zod.string()),
    }),
    name: zod
        .string()
        .max(earlyAccessFeaturePartialUpdateResponseNameMax)
        .describe('The name of the early access feature.'),
    description: zod
        .string()
        .optional()
        .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
    stage: zod
        .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
        .describe(
            '* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        )
        .describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.\n\n* `draft` - draft\n* `concept` - concept\n* `alpha` - alpha\n* `beta` - beta\n* `general-availability` - general availability\n* `archived` - archived'
        ),
    documentation_url: zod
        .url()
        .max(earlyAccessFeaturePartialUpdateResponseDocumentationUrlMax)
        .optional()
        .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
    payload: zod.record(zod.string(), zod.unknown()).describe('Feature flag payload for this early access feature'),
    created_at: zod.iso.datetime({}),
})
