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

export const docsDiscussionsCreateBodyKindDefault = `text`
export const docsDiscussionsCreateBodyTaskIdMax = 64

export const docsDiscussionsCreateBodyEvidenceItemLabelMax = 120

export const docsDiscussionsCreateBodySendToAgentDefault = false

export const DocsDiscussionsCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().describe('The first message.'),
        anchor_key: zod
            .string()
            .max(docsDiscussionsCreateBodyAnchorKeyMax)
            .describe('Key the client also writes onto the mark around the selected phrase, or the request id.'),
        anchor_text: zod
            .string()
            .max(docsDiscussionsCreateBodyAnchorTextMax)
            .describe('The selected phrase or the question, quoted in the panel.'),
        kind: zod
            .enum(['text', 'data', 'watch'])
            .describe('\* `text` - text\n\* `data` - data\n\* `watch` - watch')
            .default(docsDiscussionsCreateBodyKindDefault)
            .describe(
                'text for a phrase, data for a data point the page asked for, watch for a hypothesis to keep watching.\n\n\* `text` - text\n\* `data` - data\n\* `watch` - watch'
            ),
        task_id: zod
            .string()
            .max(docsDiscussionsCreateBodyTaskIdMax)
            .nullish()
            .describe('The agent task this thread talks to. Set by the client that started the run.'),
        evidence: zod
            .array(
                zod.object({
                    label: zod
                        .string()
                        .max(docsDiscussionsCreateBodyEvidenceItemLabelMax)
                        .describe('What the number counts.'),
                    query: zod.string().describe('One HogQL SELECT: one number, or a date and a number per row.'),
                })
            )
            .optional()
            .describe('For a watch on a number already on the page: its query. No agent and no scout are involved.'),
        send_to_agent: zod
            .boolean()
            .default(docsDiscussionsCreateBodySendToAgentDefault)
            .describe('True when the post tags the agent. With a live run the text is forwarded into it.'),
    })
    .describe('What a new thread needs.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsReplyCreateBodyTaskIdMax = 64

export const docsDiscussionsReplyCreateBodySendToAgentDefault = false

export const DocsDiscussionsReplyCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().describe('What to add to the thread.'),
        task_id: zod
            .string()
            .max(docsDiscussionsReplyCreateBodyTaskIdMax)
            .nullish()
            .describe(
                'A task the client just started for this thread. The thread keeps it; the post is not forwarded.'
            ),
        send_to_agent: zod
            .boolean()
            .default(docsDiscussionsReplyCreateBodySendToAgentDefault)
            .describe('True when the post tags the agent. With a live run the text is forwarded into it.'),
    })
    .describe('A post on an existing thread.')

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
    .describe('Mark a thread handled, or bring it back.')

/**
 * Docs: collaborative rich-text documents filed in a space.
 *
 * Live editing runs over prosemirror-collab steps on a Redis stream. This API stores the
 * durable copy and fans steps, carets, and discussion pings out over one SSE stream.
 */
export const docsDiscussionsWatchCreateBodyReasonDefault = ``
export const docsDiscussionsWatchCreateBodyReasonMax = 600

export const DocsDiscussionsWatchCreateBody = /* @__PURE__ */ zod
    .object({
        action: zod
            .enum(['check', 'stop', 'resume', 'close', 'arm'])
            .describe('\* `check` - check\n\* `stop` - stop\n\* `resume` - resume\n\* `close` - close\n\* `arm` - arm')
            .describe(
                'check runs the evidence now. stop and resume toggle the watch. close sets a final verdict. arm starts the scout when it is missing.\n\n\* `check` - check\n\* `stop` - stop\n\* `resume` - resume\n\* `close` - close\n\* `arm` - arm'
            ),
        verdict: zod
            .union([
                zod.enum(['confirmed', 'refuted']).describe('\* `confirmed` - confirmed\n\* `refuted` - refuted'),
                zod.null(),
            ])
            .optional()
            .describe('With close: confirmed or refuted.\n\n\* `confirmed` - confirmed\n\* `refuted` - refuted'),
        reason: zod
            .string()
            .max(docsDiscussionsWatchCreateBodyReasonMax)
            .default(docsDiscussionsWatchCreateBodyReasonDefault)
            .describe('With close: why.'),
    })
    .describe('What a person does to a watch.')

/**
 * Called by the agent that a page asked for a data point. The query is checked and run once; on ok the page shows it live from then on. Submit again with the same request id to replace it.
 * @summary Submit the query behind a data point
 */
export const docsDataPointsSubmitCreateBodyRequestIdMax = 64

export const docsDataPointsSubmitCreateBodyStatusDefault = `ok`
export const docsDataPointsSubmitCreateBodyQueryDefault = ``
export const docsDataPointsSubmitCreateBodyLabelDefault = ``
export const docsDataPointsSubmitCreateBodyLabelMax = 120

export const docsDataPointsSubmitCreateBodyNoteDefault = ``
export const docsDataPointsSubmitCreateBodyNoteMax = 400

export const DocsDataPointsSubmitCreateBody = /* @__PURE__ */ zod
    .object({
        request_id: zod
            .string()
            .max(docsDataPointsSubmitCreateBodyRequestIdMax)
            .describe('The request id named in the task.'),
        status: zod
            .enum(['ok', 'none'])
            .describe('\* `ok` - ok\n\* `none` - none')
            .default(docsDataPointsSubmitCreateBodyStatusDefault)
            .describe(
                "ok: the query answers the question. none: this project's data cannot answer it.\n\n\* `ok` - ok\n\* `none` - none"
            ),
        query: zod
            .string()
            .default(docsDataPointsSubmitCreateBodyQueryDefault)
            .describe('A HogQL SELECT that returns exactly one row and one column. Required unless status is none.'),
        label: zod
            .string()
            .max(docsDataPointsSubmitCreateBodyLabelMax)
            .default(docsDataPointsSubmitCreateBodyLabelDefault)
            .describe('What the data point measures, in a few words. The reader sees this on it.'),
        note: zod
            .string()
            .max(docsDataPointsSubmitCreateBodyNoteMax)
            .default(docsDataPointsSubmitCreateBodyNoteDefault)
            .describe('One short line for the reader: a caveat, or with status none, why there is no answer.'),
    })
    .describe('An agent handing in the query behind a data point a page asked for.')

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
 * Called by the agent a page asked to watch a hypothesis. Each evidence query is run once; on ok the page rechecks them daily and a scout follows the signals. Submit again with the same request id to replace the brief.
 * @summary Submit the brief behind a watch
 */
export const docsWatchesBriefCreateBodyRequestIdMax = 64

export const docsWatchesBriefCreateBodyClaimMax = 400

export const docsWatchesBriefCreateBodyConfirmsDefault = ``
export const docsWatchesBriefCreateBodyConfirmsMax = 400

export const docsWatchesBriefCreateBodyRefutesDefault = ``
export const docsWatchesBriefCreateBodyRefutesMax = 400

export const docsWatchesBriefCreateBodyEvidenceItemLabelMax = 120

export const docsWatchesBriefCreateBodySignalsItemMax = 200

export const DocsWatchesBriefCreateBody = /* @__PURE__ */ zod
    .object({
        request_id: zod
            .string()
            .max(docsWatchesBriefCreateBodyRequestIdMax)
            .describe('The request id named in the task.'),
        claim: zod
            .string()
            .max(docsWatchesBriefCreateBodyClaimMax)
            .describe('The claim in one sentence, as the page states it.'),
        confirms: zod
            .string()
            .max(docsWatchesBriefCreateBodyConfirmsMax)
            .default(docsWatchesBriefCreateBodyConfirmsDefault)
            .describe('What would confirm it.'),
        refutes: zod
            .string()
            .max(docsWatchesBriefCreateBodyRefutesMax)
            .default(docsWatchesBriefCreateBodyRefutesDefault)
            .describe('What would refute it.'),
        evidence: zod
            .array(
                zod.object({
                    label: zod
                        .string()
                        .max(docsWatchesBriefCreateBodyEvidenceItemLabelMax)
                        .describe('What the number counts.'),
                    query: zod.string().describe('One HogQL SELECT: one number, or a date and a number per row.'),
                })
            )
            .optional()
            .describe('Up to four numbers the claim stands on.'),
        signals: zod
            .array(zod.string().max(docsWatchesBriefCreateBodySignalsItemMax))
            .optional()
            .describe('Up to six things the scout follows: events, flags, experiments, error issues, replay filters.'),
    })
    .describe('An agent handing in the brief behind a watch.')

/**
 * Called by the agent that watches a hypothesis, after it looked at the data. Confirmed and refuted end the watch.
 * @summary Set the verdict on a watched hypothesis
 */
export const docsWatchesVerdictCreateBodyRequestIdMax = 64

export const docsWatchesVerdictCreateBodyReasonMax = 600

export const DocsWatchesVerdictCreateBody = /* @__PURE__ */ zod
    .object({
        request_id: zod
            .string()
            .max(docsWatchesVerdictCreateBodyRequestIdMax)
            .describe('The request id named in the task.'),
        verdict: zod
            .enum(['holding', 'moved', 'confirmed', 'refuted'])
            .describe('\* `holding` - holding\n\* `moved` - moved\n\* `confirmed` - confirmed\n\* `refuted` - refuted')
            .describe(
                'holding, moved, confirmed, or refuted. Confirmed and refuted end the watch.\n\n\* `holding` - holding\n\* `moved` - moved\n\* `confirmed` - confirmed\n\* `refuted` - refuted'
            ),
        reason: zod.string().max(docsWatchesVerdictCreateBodyReasonMax).describe('Why, in one line the reader sees.'),
    })
    .describe('An agent saying where the claim stands.')

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
