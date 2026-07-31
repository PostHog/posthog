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

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const productTourApiNameMax = 400

export const ProductTourApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productTourApiNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: MinimalFeatureFlagApi,
        linked_flag: MinimalFeatureFlagApi,
        targeting_flag_filters: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
        content: zod.unknown().optional(),
        draft_content: zod.unknown(),
        has_draft: zod.boolean(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        updated_at: zod.iso.datetime({ offset: true }),
        archived: zod.boolean().optional(),
        search_match_type: zod
            .union([SearchMatchTypeEnumApi, zod.null()])
            .describe(
                'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
            ),
    })
    .describe('Read-only serializer for ProductTour.')

export type ProductTourApi = zod.input<typeof ProductTourApi>
export type ProductTourApiOutput = zod.output<typeof ProductTourApi>

export const PaginatedProductTourListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ProductTourApi),
})

export type PaginatedProductTourListApi = zod.input<typeof PaginatedProductTourListApi>
export type PaginatedProductTourListApiOutput = zod.output<typeof PaginatedProductTourListApi>

export const ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi = zod
    .enum(['app', 'toolbar'])
    .describe('\* `app` - app\n\* `toolbar` - toolbar')

export type ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi = zod.input<
    typeof ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi
>
export type ProductTourSerializerCreateUpdateOnlyCreationContextEnumApiOutput = zod.output<
    typeof ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi
>

export const productTourSerializerCreateUpdateOnlyApiNameMax = 400

export const productTourSerializerCreateUpdateOnlyApiCreationContextDefault = `app`

export const ProductTourSerializerCreateUpdateOnlyApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productTourSerializerCreateUpdateOnlyApiNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: MinimalFeatureFlagApi,
        linked_flag: MinimalFeatureFlagApi,
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().optional(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        updated_at: zod.iso.datetime({ offset: true }),
        archived: zod.boolean().optional(),
        creation_context: ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi.default(
            productTourSerializerCreateUpdateOnlyApiCreationContextDefault
        ).describe('Where the tour was created\/updated from\n\n\* `app` - app\n\* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export type ProductTourSerializerCreateUpdateOnlyApi = zod.input<typeof ProductTourSerializerCreateUpdateOnlyApi>
export type ProductTourSerializerCreateUpdateOnlyApiOutput = zod.output<typeof ProductTourSerializerCreateUpdateOnlyApi>

export const patchedProductTourSerializerCreateUpdateOnlyApiNameMax = 400

export const patchedProductTourSerializerCreateUpdateOnlyApiCreationContextDefault = `app`

export const PatchedProductTourSerializerCreateUpdateOnlyApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().max(patchedProductTourSerializerCreateUpdateOnlyApiNameMax).optional(),
        description: zod.string().optional(),
        internal_targeting_flag: MinimalFeatureFlagApi.optional(),
        linked_flag: MinimalFeatureFlagApi.optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().optional(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        archived: zod.boolean().optional(),
        creation_context: ProductTourSerializerCreateUpdateOnlyCreationContextEnumApi.default(
            patchedProductTourSerializerCreateUpdateOnlyApiCreationContextDefault
        ).describe('Where the tour was created\/updated from\n\n\* `app` - app\n\* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export type PatchedProductTourSerializerCreateUpdateOnlyApi = zod.input<
    typeof PatchedProductTourSerializerCreateUpdateOnlyApi
>
export type PatchedProductTourSerializerCreateUpdateOnlyApiOutput = zod.output<
    typeof PatchedProductTourSerializerCreateUpdateOnlyApi
>

export const DraftStatusResponseApi = zod.object({
    updated_at: zod.iso.datetime({ offset: true }),
    has_draft: zod.boolean(),
})

export type DraftStatusResponseApi = zod.input<typeof DraftStatusResponseApi>
export type DraftStatusResponseApiOutput = zod.output<typeof DraftStatusResponseApi>

export const generateRequestApiTitleDefault = ``
export const generateRequestApiGoalDefault = ``

export const GenerateRequestApi = zod.object({
    title: zod.string().default(generateRequestApiTitleDefault),
    goal: zod.string().default(generateRequestApiGoalDefault),
    steps: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
})

export type GenerateRequestApi = zod.input<typeof GenerateRequestApi>
export type GenerateRequestApiOutput = zod.output<typeof GenerateRequestApi>

export const GenerateStepResponseApi = zod.object({
    step_id: zod.string(),
    title: zod.string(),
    description: zod.string(),
})

export type GenerateStepResponseApi = zod.input<typeof GenerateStepResponseApi>
export type GenerateStepResponseApiOutput = zod.output<typeof GenerateStepResponseApi>

export const GenerateResponseApi = zod.object({
    steps: zod.array(GenerateStepResponseApi),
})

export type GenerateResponseApi = zod.input<typeof GenerateResponseApi>
export type GenerateResponseApiOutput = zod.output<typeof GenerateResponseApi>
