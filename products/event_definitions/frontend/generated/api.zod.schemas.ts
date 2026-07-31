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

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

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

export const EnforcementModeEnumApi = zod.enum(['allow', 'reject']).describe('\* `allow` - Allow\n\* `reject` - Reject')

export type EnforcementModeEnumApi = zod.input<typeof EnforcementModeEnumApi>
export type EnforcementModeEnumApiOutput = zod.output<typeof EnforcementModeEnumApi>

export const enterpriseEventDefinitionApiNameMax = 400

export const enterpriseEventDefinitionApiPrimaryPropertyMax = 400

export const enterpriseEventDefinitionApiPostToSlackDefault = false

export const EnterpriseEventDefinitionApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(enterpriseEventDefinitionApiNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        created_at: zod.iso.datetime({ offset: true }).nullable(),
        updated_at: zod.iso.datetime({ offset: true }),
        updated_by: UserBasicApi,
        last_seen_at: zod.iso.datetime({ offset: true }).nullable(),
        last_updated_at: zod.iso.datetime({ offset: true }),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({ offset: true }).nullable(),
        verified_by: UserBasicApi,
        hidden: zod.boolean().nullish(),
        enforcement_mode: EnforcementModeEnumApi.optional(),
        primary_property: zod
            .string()
            .max(enterpriseEventDefinitionApiPrimaryPropertyMax)
            .nullish()
            .describe(
                "Name of a single property on this event that PostHog UIs should display alongside the event (for example `$pathname` on `$pageview`). When set, surfaces like the session replay inspector show the property's value next to the event name without the user having to open the event."
            ),
        is_action: zod.boolean(),
        action_id: zod.number(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        post_to_slack: zod.boolean().default(enterpriseEventDefinitionApiPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
        media_preview_urls: zod.array(zod.string()),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type EnterpriseEventDefinitionApi = zod.input<typeof EnterpriseEventDefinitionApi>
export type EnterpriseEventDefinitionApiOutput = zod.output<typeof EnterpriseEventDefinitionApi>

export const PaginatedEnterpriseEventDefinitionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EnterpriseEventDefinitionApi),
})

export type PaginatedEnterpriseEventDefinitionListApi = zod.input<typeof PaginatedEnterpriseEventDefinitionListApi>
export type PaginatedEnterpriseEventDefinitionListApiOutput = zod.output<
    typeof PaginatedEnterpriseEventDefinitionListApi
>

export const patchedEnterpriseEventDefinitionApiNameMax = 400

export const patchedEnterpriseEventDefinitionApiPrimaryPropertyMax = 400

export const patchedEnterpriseEventDefinitionApiPostToSlackDefault = false

export const PatchedEnterpriseEventDefinitionApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().max(patchedEnterpriseEventDefinitionApiNameMax).optional(),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        updated_by: UserBasicApi.optional(),
        last_seen_at: zod.iso.datetime({ offset: true }).nullish(),
        last_updated_at: zod.iso.datetime({ offset: true }).optional(),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({ offset: true }).nullish(),
        verified_by: UserBasicApi.optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: EnforcementModeEnumApi.optional(),
        primary_property: zod
            .string()
            .max(patchedEnterpriseEventDefinitionApiPrimaryPropertyMax)
            .nullish()
            .describe(
                "Name of a single property on this event that PostHog UIs should display alongside the event (for example `$pathname` on `$pageview`). When set, surfaces like the session replay inspector show the property's value next to the event name without the user having to open the event."
            ),
        is_action: zod.boolean().optional(),
        action_id: zod.number().optional(),
        is_calculating: zod.boolean().optional(),
        last_calculated_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
        post_to_slack: zod.boolean().default(patchedEnterpriseEventDefinitionApiPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
        media_preview_urls: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type PatchedEnterpriseEventDefinitionApi = zod.input<typeof PatchedEnterpriseEventDefinitionApi>
export type PatchedEnterpriseEventDefinitionApiOutput = zod.output<typeof PatchedEnterpriseEventDefinitionApi>

export const BulkUpdateTagsActionEnumApi = zod
    .enum(['add', 'remove', 'set'])
    .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')

export type BulkUpdateTagsActionEnumApi = zod.input<typeof BulkUpdateTagsActionEnumApi>
export type BulkUpdateTagsActionEnumApiOutput = zod.output<typeof BulkUpdateTagsActionEnumApi>

export const bulkUpdateTagsUUIDRequestApiIdsMax = 500

export const BulkUpdateTagsUUIDRequestApi = zod
    .object({
        ids: zod
            .array(zod.uuid())
            .max(bulkUpdateTagsUUIDRequestApiIdsMax)
            .describe('List of object UUIDs to update tags on.'),
        action: BulkUpdateTagsActionEnumApi.describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
        ),
        tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
    })
    .describe('Variant of ``BulkUpdateTagsRequestSerializer`` for resources keyed by UUID (e.g. event definitions).')

export type BulkUpdateTagsUUIDRequestApi = zod.input<typeof BulkUpdateTagsUUIDRequestApi>
export type BulkUpdateTagsUUIDRequestApiOutput = zod.output<typeof BulkUpdateTagsUUIDRequestApi>

export const BulkUpdateTagsUUIDItemApi = zod.object({
    id: zod.uuid().describe('UUID of the object whose tags were updated.'),
    tags: zod.array(zod.string()).describe("The object's full tag list after the update."),
})

export type BulkUpdateTagsUUIDItemApi = zod.input<typeof BulkUpdateTagsUUIDItemApi>
export type BulkUpdateTagsUUIDItemApiOutput = zod.output<typeof BulkUpdateTagsUUIDItemApi>

export const BulkUpdateTagsUUIDErrorApi = zod.object({
    id: zod.uuid().describe('UUID of the object that was skipped.'),
    reason: zod.string().describe("Why the object was skipped, e.g. 'Not found'."),
})

export type BulkUpdateTagsUUIDErrorApi = zod.input<typeof BulkUpdateTagsUUIDErrorApi>
export type BulkUpdateTagsUUIDErrorApiOutput = zod.output<typeof BulkUpdateTagsUUIDErrorApi>

export const BulkUpdateTagsUUIDResponseApi = zod.object({
    updated: zod.array(BulkUpdateTagsUUIDItemApi).describe('Objects whose tags were successfully updated.'),
    skipped: zod.array(BulkUpdateTagsUUIDErrorApi).describe('Objects that were skipped, with a reason each.'),
})

export type BulkUpdateTagsUUIDResponseApi = zod.input<typeof BulkUpdateTagsUUIDResponseApi>
export type BulkUpdateTagsUUIDResponseApiOutput = zod.output<typeof BulkUpdateTagsUUIDResponseApi>

export const eventDefinitionRecordApiNameMax = 400

export const eventDefinitionRecordApiPrimaryPropertyMax = 400

export const eventDefinitionRecordApiPostToSlackDefault = false

export const EventDefinitionRecordApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(eventDefinitionRecordApiNameMax),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        last_seen_at: zod.iso.datetime({ offset: true }).nullish(),
        last_updated_at: zod.iso.datetime({ offset: true }),
        tags: zod.array(zod.unknown()).optional(),
        enforcement_mode: EnforcementModeEnumApi.optional(),
        primary_property: zod
            .string()
            .max(eventDefinitionRecordApiPrimaryPropertyMax)
            .nullish()
            .describe(
                "Name of a single property on this event that PostHog UIs should display alongside the event (for example `$pathname` on `$pageview`). When set, surfaces like the session replay inspector show the property's value next to the event name without the user having to open the event."
            ),
        is_action: zod.boolean(),
        action_id: zod.number(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        post_to_slack: zod.boolean().default(eventDefinitionRecordApiPostToSlackDefault),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type EventDefinitionRecordApi = zod.input<typeof EventDefinitionRecordApi>
export type EventDefinitionRecordApiOutput = zod.output<typeof EventDefinitionRecordApi>

export const PrimaryPropertiesResponseApi = zod.object({
    primary_properties: zod
        .record(zod.string(), zod.string())
        .describe(
            'Mapping from event name to the team-configured primary property for that event. Names without a configured primary property are omitted; callers should fall back to the core taxonomy defaults for those.'
        ),
})

export type PrimaryPropertiesResponseApi = zod.input<typeof PrimaryPropertiesResponseApi>
export type PrimaryPropertiesResponseApiOutput = zod.output<typeof PrimaryPropertiesResponseApi>
