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

export const FieldNoteStatusEnumApi = zod
    .enum(['pending', 'acknowledged', 'resolved', 'dismissed'])
    .describe(
        '\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
    )

export type FieldNoteStatusEnumApi = zod.input<typeof FieldNoteStatusEnumApi>
export type FieldNoteStatusEnumApiOutput = zod.output<typeof FieldNoteStatusEnumApi>

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

export const fieldNoteApiCommentMax = 5000

export const fieldNoteApiUrlMax = 2048

export const fieldNoteApiHostMax = 255

export const fieldNoteApiPathnameMax = 2048

export const fieldNoteApiSelectorMax = 4096

export const fieldNoteApiElementTextMax = 2048

export const fieldNoteApiElementChainMax = 20000

export const fieldNoteApiScreenshotUrlMax = 2048

export const FieldNoteApi = zod.object({
    id: zod.uuid(),
    comment: zod.string().max(fieldNoteApiCommentMax).describe('The note the user wrote about the element.'),
    field_note_status: FieldNoteStatusEnumApi.optional().describe(
        'Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
    ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the field note.'),
    url: zod.string().max(fieldNoteApiUrlMax).describe('Full URL of the page the field note was made on.'),
    host: zod.string().max(fieldNoteApiHostMax).describe('Hostname of the page, used to scope field notes to a site.'),
    pathname: zod.string().max(fieldNoteApiPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod.string().max(fieldNoteApiSelectorMax).describe('CSS selector that locates the element on the page.'),
    element_text: zod
        .string()
        .max(fieldNoteApiElementTextMax)
        .nullish()
        .describe('Visible text of the element, if any.'),
    element_chain: zod
        .string()
        .max(fieldNoteApiElementChainMax)
        .nullish()
        .describe('Serialized autocapture-style element chain from the element up to the document root.'),
    element_context: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Structured element metadata (inferred selectors, attributes, component hints).'),
    viewport: zod
        .object({
            width: zod.number().optional().describe('Viewport width in pixels.'),
            height: zod.number().optional().describe('Viewport height in pixels.'),
        })
        .nullish()
        .describe('Viewport size when the field note was made, as {width, height}.'),
    screenshot_url: zod
        .string()
        .max(fieldNoteApiScreenshotUrlMax)
        .nullish()
        .describe('URL of an uploaded screenshot captured with the field_note.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: UserBasicApi,
})

export type FieldNoteApi = zod.input<typeof FieldNoteApi>
export type FieldNoteApiOutput = zod.output<typeof FieldNoteApi>

export const PaginatedFieldNoteListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(FieldNoteApi),
})

export type PaginatedFieldNoteListApi = zod.input<typeof PaginatedFieldNoteListApi>
export type PaginatedFieldNoteListApiOutput = zod.output<typeof PaginatedFieldNoteListApi>

export const patchedFieldNoteApiCommentMax = 5000

export const patchedFieldNoteApiUrlMax = 2048

export const patchedFieldNoteApiHostMax = 255

export const patchedFieldNoteApiPathnameMax = 2048

export const patchedFieldNoteApiSelectorMax = 4096

export const patchedFieldNoteApiElementTextMax = 2048

export const patchedFieldNoteApiElementChainMax = 20000

export const patchedFieldNoteApiScreenshotUrlMax = 2048

export const PatchedFieldNoteApi = zod.object({
    id: zod.uuid().optional(),
    comment: zod
        .string()
        .max(patchedFieldNoteApiCommentMax)
        .optional()
        .describe('The note the user wrote about the element.'),
    field_note_status: FieldNoteStatusEnumApi.optional().describe(
        'Lifecycle of the field note: pending, acknowledged, resolved, or dismissed. Ignored on create.\n\n\* `pending` - Pending\n\* `acknowledged` - Acknowledged\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
    ),
    resolution: zod
        .string()
        .nullish()
        .describe('Optional note left by the agent when acknowledging, resolving, or dismissing the field note.'),
    url: zod
        .string()
        .max(patchedFieldNoteApiUrlMax)
        .optional()
        .describe('Full URL of the page the field note was made on.'),
    host: zod
        .string()
        .max(patchedFieldNoteApiHostMax)
        .optional()
        .describe('Hostname of the page, used to scope field notes to a site.'),
    pathname: zod.string().max(patchedFieldNoteApiPathnameMax).nullish().describe('Path portion of the URL.'),
    selector: zod
        .string()
        .max(patchedFieldNoteApiSelectorMax)
        .optional()
        .describe('CSS selector that locates the element on the page.'),
    element_text: zod
        .string()
        .max(patchedFieldNoteApiElementTextMax)
        .nullish()
        .describe('Visible text of the element, if any.'),
    element_chain: zod
        .string()
        .max(patchedFieldNoteApiElementChainMax)
        .nullish()
        .describe('Serialized autocapture-style element chain from the element up to the document root.'),
    element_context: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Structured element metadata (inferred selectors, attributes, component hints).'),
    viewport: zod
        .object({
            width: zod.number().optional().describe('Viewport width in pixels.'),
            height: zod.number().optional().describe('Viewport height in pixels.'),
        })
        .nullish()
        .describe('Viewport size when the field note was made, as {width, height}.'),
    screenshot_url: zod
        .string()
        .max(patchedFieldNoteApiScreenshotUrlMax)
        .nullish()
        .describe('URL of an uploaded screenshot captured with the field_note.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
    created_by: UserBasicApi.optional(),
})

export type PatchedFieldNoteApi = zod.input<typeof PatchedFieldNoteApi>
export type PatchedFieldNoteApiOutput = zod.output<typeof PatchedFieldNoteApi>
