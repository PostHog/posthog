/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Send one push notification from a push template made transactional to every device of one person. `message_data` fills the template's `{{ variables.* }}` placeholders. Transactional push notifications skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry safely without sending the notification twice. Needs the `transactional_push:write` scope. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too.
 * @summary Send a transactional push notification
 */
export const MessagingSendPushCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingSendPushCreateHeader = () => zod.object({
    'Idempotency-Key': zod
        .string()
        .optional()
        .describe(
            "A unique key for this email, 1 to 255 visible ASCII characters. Retrying with the same key and the same request within 24 hours sends nothing new and returns the first send's `message_id`. Reusing a key for a different request returns a 422."
        ),
})

export const messagingSendPushCreateBodyDistinctIdMax = 400

export const MessagingSendPushCreateBody = () => zod.object({
    template_id: zod
        .string()
        .describe(
            "ID of a push template made transactional, which holds the notification's title, body and push channels."
        ),
    distinct_id: zod
        .string()
        .max(messagingSendPushCreateBodyDistinctIdMax)
        .describe(
            "Distinct ID of the person to notify. The notification goes to every device this person registered for the template's push channels. A person with no registered device gets nothing, and the send shows as skipped in the template's sends. The template can't read the person's properties, so pass everything it needs in `message_data`."
        ),
    message_data: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe("Values for the template's {{ variables.\* }} placeholders, keyed by variable name."),
})

export const MessagingTemplatesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyTagsItemMax = 255

export const messagingTemplatesCreateBodyTagsMax = 10

export const messagingTemplatesCreateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesCreateBodyContentOnePushOneTitleMax = 1000

export const messagingTemplatesCreateBodyContentOnePushOneBodyMax = 4000

export const messagingTemplatesCreateBodyContentOnePushOneImageMax = 2000

export const messagingTemplatesCreateBodyContentOnePushOneLinkMax = 2000

export const messagingTemplatesCreateBodyContentOnePushOneChannelsMax = 20

export const messagingTemplatesCreateBodyContentOnePushOneDataMaxOne = 4000

export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = () => zod.object({
    name: zod
        .string()
        .max(messagingTemplatesCreateBodyNameMax)
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    tags: zod
        .array(zod.string().max(messagingTemplatesCreateBodyTagsItemMax))
        .max(messagingTemplatesCreateBodyTagsMax)
        .optional()
        .describe(
            'Tags for organizing templates, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.'
        ),
    content: zod
        .object({
            templating: zod
                .enum(['liquid'])
                .describe('\* `liquid` - liquid')
                .default(messagingTemplatesCreateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n\* `liquid` - liquid"
                ),
            push: zod
                .union([
                    zod.object({
                        title: zod
                            .string()
                            .max(messagingTemplatesCreateBodyContentOnePushOneTitleMax)
                            .optional()
                            .describe(
                                'Notification title. Supports Liquid templating, such as {{ variables.name }}. Required in `content` for push-type templates.'
                            ),
                        body: zod
                            .string()
                            .max(messagingTemplatesCreateBodyContentOnePushOneBodyMax)
                            .optional()
                            .describe(
                                'Notification body text. Supports Liquid templating. Required in `content` for push-type templates.'
                            ),
                        image: zod
                            .string()
                            .max(messagingTemplatesCreateBodyContentOnePushOneImageMax)
                            .optional()
                            .describe('URL of an image to show in the notification. Supports Liquid templating.'),
                        link: zod
                            .string()
                            .max(messagingTemplatesCreateBodyContentOnePushOneLinkMax)
                            .optional()
                            .describe(
                                'Where a tap should take the person, such as myapp:\/\/orders\/123 or a web URL. Sent to the app as the \"link\" key in the custom data. Supports Liquid templating.'
                            ),
                        channels: zod
                            .array(zod.number())
                            .max(messagingTemplatesCreateBodyContentOnePushOneChannelsMax)
                            .optional()
                            .describe(
                                "IDs of the project's Firebase and APNs integrations to send through. Each person gets the notification on every device they registered with one of these apps."
                            ),
                        data: zod
                            .record(
                                zod.string(),
                                zod.string().max(messagingTemplatesCreateBodyContentOnePushOneDataMaxOne)
                            )
                            .optional()
                            .describe(
                                'Custom key-value data delivered to the app. Values are strings and support Liquid templating.'
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    'Push notification content, for push-type templates. Replaced as a whole on update — send the complete object.'
                ),
        })
        .optional()
        .describe('Template content keyed by channel. Replaced as a whole on update, not merged.'),
    type: zod
        .string()
        .max(messagingTemplatesCreateBodyTypeMax)
        .optional()
        .describe("Message channel of the template: 'email' (the default) or 'push'."),
    message_category: zod
        .string()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
})

/**
 * Make this template sendable over the transactional email API, or the transactional push API for a push template. This creates the workflow that sends it, with its own metrics, run history and versions. This can't be undone: the template stays transactional. Transactional sends ignore marketing opt-outs. Calling it again on a transactional template changes nothing. Needs the `transactional_email:write` scope, the same scope as sending. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too. Without `hog_flow:read`, the response leaves out `content` and `draft_content`.
 * @summary Make a template transactional
 */
export const MessagingTemplatesMakeTransactionalCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingTemplatesMakeTransactionalCreateBody = () => zod.looseObject({})
