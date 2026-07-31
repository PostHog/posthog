/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const EvaluationRuntimeEnumApi = zod
    .enum(['server', 'client', 'all'])
    .describe('\* `server` - Server\n\* `client` - Client\n\* `all` - All')

export type EvaluationRuntimeEnumApi = zod.input<typeof EvaluationRuntimeEnumApi>
export type EvaluationRuntimeEnumApiOutput = zod.output<typeof EvaluationRuntimeEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const BucketingIdentifierEnumApi = zod
    .enum(['distinct_id', 'device_id'])
    .describe('\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID')

export type BucketingIdentifierEnumApi = zod.input<typeof BucketingIdentifierEnumApi>
export type BucketingIdentifierEnumApiOutput = zod.output<typeof BucketingIdentifierEnumApi>

export const minimalFeatureFlagApiKeyMax = 400

export const minimalFeatureFlagApiVersionMin = -2147483648
export const minimalFeatureFlagApiVersionMax = 2147483647

export const MinimalFeatureFlagApi = zod.object({
    id: zod.number(),
    team_id: zod.number(),
    name: zod.string().optional(),
    key: zod.string().max(minimalFeatureFlagApiKeyMax),
    filters: zod.record(zod.string(), zod.unknown()).optional(),
    deleted: zod.boolean().optional(),
    active: zod.boolean().optional(),
    ensure_experience_continuity: zod.boolean().nullish(),
    version: zod.number().min(minimalFeatureFlagApiVersionMin).max(minimalFeatureFlagApiVersionMax).nullish(),
    evaluation_runtime: zod
        .union([EvaluationRuntimeEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Specifies where this feature flag should be evaluated\n\n\* `server` - Server\n\* `client` - Client\n\* `all` - All'
        ),
    bucketing_identifier: zod
        .union([BucketingIdentifierEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Identifier used for bucketing users into rollout and variants\n\n\* `distinct_id` - User ID (default)\n\* `device_id` - Device ID'
        ),
    evaluation_contexts: zod.array(zod.string()),
})

export type MinimalFeatureFlagApi = zod.input<typeof MinimalFeatureFlagApi>
export type MinimalFeatureFlagApiOutput = zod.output<typeof MinimalFeatureFlagApi>

export const StageEnumApi = zod
    .enum(['draft', 'concept', 'alpha', 'beta', 'general-availability', 'archived'])
    .describe(
        '\* `draft` - draft\n\* `concept` - concept\n\* `alpha` - alpha\n\* `beta` - beta\n\* `general-availability` - general availability\n\* `archived` - archived'
    )

export type StageEnumApi = zod.input<typeof StageEnumApi>
export type StageEnumApiOutput = zod.output<typeof StageEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const earlyAccessFeatureApiNameMax = 200

export const earlyAccessFeatureApiDocumentationUrlMax = 800

export const EarlyAccessFeatureApi = zod
    .object({
        id: zod.uuid(),
        feature_flag: MinimalFeatureFlagApi,
        name: zod.string().max(earlyAccessFeatureApiNameMax).describe('The name of the early access feature.'),
        description: zod
            .string()
            .optional()
            .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
        stage: StageEnumApi.describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha\/beta\/general-availability) enables the feature flag for opted-in users.\n\n\* `draft` - draft\n\* `concept` - concept\n\* `alpha` - alpha\n\* `beta` - beta\n\* `general-availability` - general availability\n\* `archived` - archived'
        ),
        documentation_url: zod
            .url()
            .max(earlyAccessFeatureApiDocumentationUrlMax)
            .optional()
            .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
        payload: zod.record(zod.string(), zod.unknown()).describe('Feature flag payload for this early access feature'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod
            .union([UserBasicApi, zod.null()])
            .describe(
                'The user who created this early access feature. Null for features created before creator tracking was added.'
            ),
        assignee: zod
            .object({
                type: zod.enum(['user', 'role']).optional(),
                id: zod.union([zod.number(), zod.string()]).optional(),
            })
            .nullable()
            .describe(
                'The person or role responsible for this feature, e.g. {\"type\": \"user\", \"id\": 123} or {\"type\": \"role\", \"id\": \"<role uuid>\"}. Defaults to the creator. Send null to unassign.'
            ),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type EarlyAccessFeatureApi = zod.input<typeof EarlyAccessFeatureApi>
export type EarlyAccessFeatureApiOutput = zod.output<typeof EarlyAccessFeatureApi>

export const PaginatedEarlyAccessFeatureListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EarlyAccessFeatureApi),
})

export type PaginatedEarlyAccessFeatureListApi = zod.input<typeof PaginatedEarlyAccessFeatureListApi>
export type PaginatedEarlyAccessFeatureListApiOutput = zod.output<typeof PaginatedEarlyAccessFeatureListApi>

export const earlyAccessFeatureSerializerCreateOnlyApiNameMax = 200

export const earlyAccessFeatureSerializerCreateOnlyApiDocumentationUrlMax = 800

export const EarlyAccessFeatureSerializerCreateOnlyApi = zod
    .object({
        id: zod.uuid(),
        name: zod
            .string()
            .max(earlyAccessFeatureSerializerCreateOnlyApiNameMax)
            .describe('The name of the early access feature.'),
        description: zod
            .string()
            .optional()
            .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
        stage: StageEnumApi.describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha\/beta\/general-availability) enables the feature flag for opted-in users.\n\n\* `draft` - draft\n\* `concept` - concept\n\* `alpha` - alpha\n\* `beta` - beta\n\* `general-availability` - general availability\n\* `archived` - archived'
        ),
        documentation_url: zod
            .url()
            .max(earlyAccessFeatureSerializerCreateOnlyApiDocumentationUrlMax)
            .optional()
            .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
        payload: zod.unknown().optional().describe('Arbitrary JSON metadata associated with this feature.'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod
            .union([UserBasicApi, zod.null()])
            .describe(
                'The user who created this early access feature. Null for features created before creator tracking was added.'
            ),
        assignee: zod
            .object({
                type: zod.enum(['user', 'role']).optional(),
                id: zod.union([zod.number(), zod.string()]).optional(),
            })
            .nullable()
            .describe(
                'The person or role responsible for this feature, e.g. {\"type\": \"user\", \"id\": 123} or {\"type\": \"role\", \"id\": \"<role uuid>\"}. Defaults to the creator. Send null to unassign.'
            ),
        feature_flag_id: zod
            .number()
            .optional()
            .describe(
                'Optional ID of an existing feature flag to link. If omitted, a new flag is auto-created from the feature name. The flag must not already be linked to another feature, must not be group-based, and must not be multivariate.'
            ),
        feature_flag: MinimalFeatureFlagApi,
        _create_in_folder: zod.string().optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type EarlyAccessFeatureSerializerCreateOnlyApi = zod.input<typeof EarlyAccessFeatureSerializerCreateOnlyApi>
export type EarlyAccessFeatureSerializerCreateOnlyApiOutput = zod.output<
    typeof EarlyAccessFeatureSerializerCreateOnlyApi
>

export const patchedEarlyAccessFeatureApiNameMax = 200

export const patchedEarlyAccessFeatureApiDocumentationUrlMax = 800

export const PatchedEarlyAccessFeatureApi = zod
    .object({
        id: zod.uuid().optional(),
        feature_flag: MinimalFeatureFlagApi.optional(),
        name: zod
            .string()
            .max(patchedEarlyAccessFeatureApiNameMax)
            .optional()
            .describe('The name of the early access feature.'),
        description: zod
            .string()
            .optional()
            .describe('A longer description of what this early access feature does, shown to users in the opt-in UI.'),
        stage: StageEnumApi.optional().describe(
            'Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha\/beta\/general-availability) enables the feature flag for opted-in users.\n\n\* `draft` - draft\n\* `concept` - concept\n\* `alpha` - alpha\n\* `beta` - beta\n\* `general-availability` - general availability\n\* `archived` - archived'
        ),
        documentation_url: zod
            .url()
            .max(patchedEarlyAccessFeatureApiDocumentationUrlMax)
            .optional()
            .describe('URL to external documentation for this feature. Shown to users in the opt-in UI.'),
        payload: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe('Feature flag payload for this early access feature'),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod
            .union([UserBasicApi, zod.null()])
            .optional()
            .describe(
                'The user who created this early access feature. Null for features created before creator tracking was added.'
            ),
        assignee: zod
            .object({
                type: zod.enum(['user', 'role']).optional(),
                id: zod.union([zod.number(), zod.string()]).optional(),
            })
            .nullish()
            .describe(
                'The person or role responsible for this feature, e.g. {\"type\": \"user\", \"id\": 123} or {\"type\": \"role\", \"id\": \"<role uuid>\"}. Defaults to the creator. Send null to unassign.'
            ),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type PatchedEarlyAccessFeatureApi = zod.input<typeof PatchedEarlyAccessFeatureApi>
export type PatchedEarlyAccessFeatureApiOutput = zod.output<typeof PatchedEarlyAccessFeatureApi>
