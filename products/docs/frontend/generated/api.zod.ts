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

/**
 * The numbers a space watches, shown on its home view.
 */
export const docKpisCreateBodyNameMax = 200

export const docKpisCreateBodyInsightShortIdMax = 32

export const DocKpisCreateBody = /* @__PURE__ */ zod
    .object({
        channel: zod.uuid().describe('The space (channel) that watches this number.'),
        name: zod.string().max(docKpisCreateBodyNameMax).describe('Label shown above the number.'),
        insight_short_id: zod
            .string()
            .max(docKpisCreateBodyInsightShortIdMax)
            .describe('Short id of the saved insight the value comes from.'),
    })
    .describe('What a new number needs.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsCreateBodyTitleMax = 400

export const docsCreateBodyTemplateDefault = `blank`

export const DocsCreateBody = /* @__PURE__ */ zod
    .object({
        channel: zod.uuid().describe('The space (channel) the doc belongs to.'),
        title: zod
            .string()
            .max(docsCreateBodyTitleMax)
            .optional()
            .describe('Title of the doc. Defaults to the template name.'),
        template: zod
            .enum(['blank', 'notes'])
            .describe('\* `blank` - blank\n\* `notes` - notes')
            .default(docsCreateBodyTemplateDefault)
            .describe(
                "Starting content: 'blank' is an empty page, 'notes' has headings for notes from a call.\n\n\* `blank` - blank\n\* `notes` - notes"
            ),
    })
    .describe('What a new doc needs.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsPartialUpdateBodyTitleMax = 400

export const DocsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        title: zod.string().max(docsPartialUpdateBodyTitleMax).optional().describe('New title for the doc.'),
        status: zod
            .enum(['draft', 'active', 'done'])
            .describe('\* `draft` - draft\n\* `active` - active\n\* `done` - done')
            .optional()
            .describe(
                'Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.\n\n\* `draft` - draft\n\* `active` - active\n\* `done` - done'
            ),
    })
    .describe('The parts of a doc a person can change outside the editor.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsCollabPresenceCreateBodyClientIdMax = 64

export const DocsCollabPresenceCreateBody = /* @__PURE__ */ zod
    .object({
        client_id: zod
            .string()
            .max(docsCollabPresenceCreateBodyClientIdMax)
            .describe('Id of the editing client, unique per open tab.'),
        version: zod.number().describe('The collab version the caret position is relative to.'),
        cursor: zod.unknown().describe("Caret position as {'anchor': int, 'head': int}."),
    })
    .describe('A caret ping, broadcast to everyone else in the doc.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsCollabSaveCreateBodyClientIdMax = 64

export const docsCollabSaveCreateBodyTextContentDefault = ``
export const docsCollabSaveCreateBodyTitleMax = 400

export const DocsCollabSaveCreateBody = /* @__PURE__ */ zod
    .object({
        client_id: zod
            .string()
            .max(docsCollabSaveCreateBodyClientIdMax)
            .describe('Id of the editing client, unique per open tab.'),
        steps: zod
            .array(zod.unknown().describe('One prosemirror-collab step, serialized.'))
            .describe('The steps to append, in order.'),
        version: zod.number().describe('The collab version the submitted steps are based on.'),
        content: zod.record(zod.string(), zod.unknown()).describe('The whole document after the steps are applied.'),
        text_content: zod
            .string()
            .default(docsCollabSaveCreateBodyTextContentDefault)
            .describe('Plain-text mirror of the body.'),
        title: zod.string().max(docsCollabSaveCreateBodyTitleMax).optional().describe('Title to store with this save.'),
        cursor_head: zod.number().nullish().describe("The caller's caret position, broadcast with the steps."),
    })
    .describe('One batch of prosemirror-collab steps, with the document they produce.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsCreateBodyAnchorKeyMax = 64

export const docsDiscussionsCreateBodyAnchorTextMax = 280

export const DocsDiscussionsCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().describe('The first message.'),
        anchor_key: zod
            .string()
            .max(docsDiscussionsCreateBodyAnchorKeyMax)
            .describe('Key the client also writes onto the mark around the selected phrase.'),
        anchor_text: zod
            .string()
            .max(docsDiscussionsCreateBodyAnchorTextMax)
            .describe('The selected phrase, quoted in the panel.'),
    })
    .describe('What a new discussion needs.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const DocsDiscussionsReplyCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().describe('What to add to the thread.'),
    })
    .describe('A reply to an existing discussion.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const DocsDiscussionsResolveCreateBody = /* @__PURE__ */ zod
    .object({
        resolved: zod.boolean().describe('True marks the thread handled, false reopens it.'),
    })
    .describe('Mark a discussion handled, or bring it back.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const DocsReorderCreateBody = /* @__PURE__ */ zod
    .object({
        channel: zod.uuid().describe('The space (channel) whose docs are being reordered.'),
        doc_ids: zod
            .array(zod.uuid().describe('Id of a doc in this space.'))
            .describe('Doc ids in their new order. Ids that are not in this space are ignored.'),
    })
    .describe("The new left-to-right order of a space's tabs.")

/**
 * Run a hybrid (semantic + full-text) RAG search over the PostHog documentation via Inkeep. Returns a markdown body with title, URL, and excerpt for each match for the agent to cite back to the user.
 * @summary Search PostHog documentation
 */
export const DocsSearchBody = /* @__PURE__ */ zod.object({
    query: zod
        .string()
        .describe(
            'Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question.'
        ),
})
