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
