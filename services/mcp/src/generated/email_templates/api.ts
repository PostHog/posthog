/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const MessagingTemplatesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MessagingTemplatesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const MessagingTemplatesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(messagingTemplatesCreateBodyNameMax)
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    content: zod
        .object({
            templating: zod
                .enum(['liquid'])
                .describe('* `liquid` - liquid')
                .default(messagingTemplatesCreateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required for email-type templates.'
                            ),
                        text: zod
                            .string()
                            .optional()
                            .describe("Plain-text fallback body for clients that can't render the email."),
                        html: zod
                            .string()
                            .optional()
                            .describe(
                                "Rendered email body — derived from the design at save time. The visual editor's save path supplies it directly; omit it otherwise."
                            ),
                        design: zod
                            .object({
                                counters: zod
                                    .looseObject({})
                                    .optional()
                                    .describe(
                                        'Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.'
                                    ),
                                schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
                                body: zod.object({
                                    id: zod.string().optional().describe('Any unique string.'),
                                    rows: zod
                                        .array(zod.looseObject({}))
                                        .describe(
                                            'Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.'
                                        ),
                                    headers: zod.array(zod.looseObject({})).optional(),
                                    footers: zod.array(zod.looseObject({})).optional(),
                                    values: zod
                                        .looseObject({})
                                        .optional()
                                        .describe(
                                            "Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor."
                                        ),
                                }),
                            })
                            .optional()
                            .describe(
                                "Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill."
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Email message content. Replaced as a whole on update — send the complete object.'),
        })
        .optional()
        .describe('Template content keyed by channel. Replaced as a whole on update, not merged.'),
    type: zod
        .string()
        .max(messagingTemplatesCreateBodyTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
})

export const MessagingTemplatesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MessagingTemplatesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const messagingTemplatesPartialUpdateBodyNameMax = 400

export const messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesPartialUpdateBodyTypeMax = 24

export const MessagingTemplatesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(messagingTemplatesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    content: zod
        .object({
            templating: zod
                .enum(['liquid'])
                .describe('* `liquid` - liquid')
                .default(messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required for email-type templates.'
                            ),
                        text: zod
                            .string()
                            .optional()
                            .describe("Plain-text fallback body for clients that can't render the email."),
                        html: zod
                            .string()
                            .optional()
                            .describe(
                                "Rendered email body — derived from the design at save time. The visual editor's save path supplies it directly; omit it otherwise."
                            ),
                        design: zod
                            .object({
                                counters: zod
                                    .looseObject({})
                                    .optional()
                                    .describe(
                                        'Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.'
                                    ),
                                schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
                                body: zod.object({
                                    id: zod.string().optional().describe('Any unique string.'),
                                    rows: zod
                                        .array(zod.looseObject({}))
                                        .describe(
                                            'Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.'
                                        ),
                                    headers: zod.array(zod.looseObject({})).optional(),
                                    footers: zod.array(zod.looseObject({})).optional(),
                                    values: zod
                                        .looseObject({})
                                        .optional()
                                        .describe(
                                            "Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor."
                                        ),
                                }),
                            })
                            .optional()
                            .describe(
                                "Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill."
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Email message content. Replaced as a whole on update — send the complete object.'),
        })
        .optional()
        .describe('Template content keyed by channel. Replaced as a whole on update, not merged.'),
    type: zod
        .string()
        .max(messagingTemplatesPartialUpdateBodyTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
})
