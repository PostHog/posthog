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
 * Persistent agents and the chat each one keeps with its owner.
 */
export const hogsCreateBodyNameMax = 80

export const hogsCreateBodyEmojiDefault = `🦔`
export const hogsCreateBodyEmojiMax = 16

export const hogsCreateBodyColorDefault = `#00A884`
export const hogsCreateBodyColorMax = 16

export const hogsCreateBodyResponsibilityDefault = ``

export const HogsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogsCreateBodyNameMax).describe("The hog's display name."),
    emoji: zod
        .string()
        .max(hogsCreateBodyEmojiMax)
        .default(hogsCreateBodyEmojiDefault)
        .describe('Emoji shown as the avatar.'),
    color: zod
        .string()
        .max(hogsCreateBodyColorMax)
        .default(hogsCreateBodyColorDefault)
        .describe('Avatar background as a hex color.'),
    responsibility: zod
        .string()
        .default(hogsCreateBodyResponsibilityDefault)
        .describe('What the hog looks after. Leave blank to let the hog ask for it in its first chat.'),
    mcp_installation_ids: zod
        .array(zod.uuid())
        .optional()
        .describe("IDs of the owner's MCP store installations this hog may use."),
})

/**
 * Update a hog. A hog calls this to save its own responsibility, memory or status.
 */
export const hogsPartialUpdateBodyNameMax = 80

export const hogsPartialUpdateBodyEmojiMax = 16

export const hogsPartialUpdateBodyColorMax = 16

export const hogsPartialUpdateBodyMemoryMax = 20000

export const HogsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogsPartialUpdateBodyNameMax).optional().describe("The hog's display name."),
    emoji: zod.string().max(hogsPartialUpdateBodyEmojiMax).optional().describe('Emoji shown as the avatar.'),
    color: zod.string().max(hogsPartialUpdateBodyColorMax).optional().describe('Avatar background as a hex color.'),
    responsibility: zod
        .string()
        .optional()
        .describe("The hog's charter: what it owns, what is worth reporting, and how often it checks."),
    memory: zod
        .string()
        .max(hogsPartialUpdateBodyMemoryMax)
        .optional()
        .describe('Notes the hog keeps for its future self. Replaces the whole memory.'),
    status: zod
        .enum(['setup', 'active', 'paused'])
        .describe('\* `setup` - Setup\n\* `active` - Active\n\* `paused` - Paused')
        .optional()
        .describe(
            'setup until the hog has a charter, then active. paused stops every wake.\n\n\* `setup` - Setup\n\* `active` - Active\n\* `paused` - Paused'
        ),
    mcp_installation_ids: zod
        .array(zod.uuid())
        .optional()
        .describe("IDs of the owner's MCP store installations this hog may use."),
})

/**
 * Approve or deny an action a hog proposed. Approving wakes the hog to carry it out.
 */
export const hogsActionsDecideCreateBodyAlwaysDefault = false
export const hogsActionsDecideCreateBodyDraftMax = 8000

export const HogsActionsDecideCreateBody = /* @__PURE__ */ zod.object({
    action_id: zod.uuid().describe('ID of the action.'),
    decision: zod
        .enum(['approve', 'deny'])
        .describe('\* `approve` - Approve\n\* `deny` - Deny')
        .describe('approve or deny.\n\n\* `approve` - Approve\n\* `deny` - Deny'),
    always: zod
        .boolean()
        .default(hogsActionsDecideCreateBodyAlwaysDefault)
        .describe('Also save the decision as a standing rule for this kind of action.'),
    draft: zod
        .string()
        .max(hogsActionsDecideCreateBodyDraftMax)
        .nullish()
        .describe("An edited draft to approve in place of the hog's."),
})

/**
 * Record that the hog carried out an approved action.
 */
export const hogsActionsDoneCreateBodyResultMax = 2000

export const HogsActionsDoneCreateBody = /* @__PURE__ */ zod.object({
    action_id: zod.uuid().describe('ID of the approved action you carried out.'),
    result: zod
        .string()
        .max(hogsActionsDoneCreateBodyResultMax)
        .describe('What happened, with a link when there is one.'),
})

/**
 * Ask to do something outside PostHog. The owner's rules, or the owner, decide.
 */
export const hogsActionsProposeCreateBodyKindMax = 60

export const hogsActionsProposeCreateBodyKindRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const hogsActionsProposeCreateBodyLabelMax = 200

export const hogsActionsProposeCreateBodyDraftDefault = ``
export const hogsActionsProposeCreateBodyDraftMax = 8000

export const HogsActionsProposeCreateBody = /* @__PURE__ */ zod.object({
    kind: zod
        .string()
        .max(hogsActionsProposeCreateBodyKindMax)
        .regex(hogsActionsProposeCreateBodyKindRegExp)
        .describe(
            "A short, stable name for the class of side effect, such as slack-message, github-pr or email-send. The owner's rules match on it, so reuse the same kind for the same sort of action."
        ),
    label: zod
        .string()
        .max(hogsActionsProposeCreateBodyLabelMax)
        .describe('One line saying what you would do and to whom.'),
    draft: zod
        .string()
        .max(hogsActionsProposeCreateBodyDraftMax)
        .default(hogsActionsProposeCreateBodyDraftDefault)
        .describe('Exactly what you would send or change. The owner may edit it before approving.'),
})

/**
 * Publish a report into the owner's chat, as the hog.
 */
export const hogsReportsCreateCreateBodyTitleMax = 200

export const hogsReportsCreateCreateBodySummaryMax = 8000

export const hogsReportsCreateCreateBodyImpactDefault = ``
export const hogsReportsCreateCreateBodyImpactMax = 500

export const hogsReportsCreateCreateBodyProposalDefault = ``
export const hogsReportsCreateCreateBodyProposalMax = 4000

export const hogsReportsCreateCreateBodyEvidenceItemDescriptionMax = 500

export const hogsReportsCreateCreateBodyEvidenceItemSourceMax = 1000

export const hogsReportsCreateCreateBodyEvidenceItemKindDefault = `other`
export const hogsReportsCreateCreateBodyEvidenceMax = 20

export const HogsReportsCreateCreateBody = /* @__PURE__ */ zod.object({
    title: zod
        .string()
        .max(hogsReportsCreateCreateBodyTitleMax)
        .describe('The outcome to change, not the observation.'),
    summary: zod
        .string()
        .max(hogsReportsCreateCreateBodySummaryMax)
        .describe('The first paragraph is the lead: what is happening, to whom, since when.'),
    priority: zod
        .enum(['p0', 'p1', 'p2', 'p3', 'p4'])
        .describe('\* `p0` - P0\n\* `p1` - P1\n\* `p2` - P2\n\* `p3` - P3\n\* `p4` - P4')
        .describe(
            'p0 broken for many now, p1 hurts users today, p2 fix this week, p3 when there is time, p4 worth knowing.\n\n\* `p0` - P0\n\* `p1` - P1\n\* `p2` - P2\n\* `p3` - P3\n\* `p4` - P4'
        ),
    impact: zod
        .string()
        .max(hogsReportsCreateCreateBodyImpactMax)
        .default(hogsReportsCreateCreateBodyImpactDefault)
        .describe('One sentence that starts with the number that matters.'),
    proposal: zod
        .string()
        .max(hogsReportsCreateCreateBodyProposalMax)
        .default(hogsReportsCreateCreateBodyProposalDefault)
        .describe('What you would do, concretely enough to act on.'),
    evidence: zod
        .array(
            zod.object({
                description: zod
                    .string()
                    .max(hogsReportsCreateCreateBodyEvidenceItemDescriptionMax)
                    .describe('What this piece of evidence shows.'),
                source: zod
                    .string()
                    .max(hogsReportsCreateCreateBodyEvidenceItemSourceMax)
                    .describe('A link or an identifier a person can check, such as an insight URL or an issue ID.'),
                kind: zod
                    .enum([
                        'insight',
                        'event',
                        'error',
                        'replay',
                        'flag',
                        'experiment',
                        'survey',
                        'log',
                        'ticket',
                        'message',
                        'code',
                        'other',
                    ])
                    .describe(
                        '\* `insight` - Insight\n\* `event` - Event\n\* `error` - Error\n\* `replay` - Replay\n\* `flag` - Flag\n\* `experiment` - Experiment\n\* `survey` - Survey\n\* `log` - Log\n\* `ticket` - Ticket\n\* `message` - Message\n\* `code` - Code\n\* `other` - Other'
                    )
                    .default(hogsReportsCreateCreateBodyEvidenceItemKindDefault)
                    .describe(
                        'What kind of record the source is.\n\n\* `insight` - Insight\n\* `event` - Event\n\* `error` - Error\n\* `replay` - Replay\n\* `flag` - Flag\n\* `experiment` - Experiment\n\* `survey` - Survey\n\* `log` - Log\n\* `ticket` - Ticket\n\* `message` - Message\n\* `code` - Code\n\* `other` - Other'
                    ),
            })
        )
        .max(hogsReportsCreateCreateBodyEvidenceMax)
        .optional()
        .describe('Specific records a person can check.'),
})

/**
 * Wake the hog to implement or investigate one of its reports.
 */
export const HogsReportsFollowUpCreateBody = /* @__PURE__ */ zod.object({
    report_id: zod.uuid().describe('ID of the report.'),
    mode: zod
        .enum(['implement', 'investigate'])
        .describe('\* `implement` - Implement\n\* `investigate` - Investigate')
        .describe(
            'implement makes the proposed change. investigate finds the root cause and changes nothing.\n\n\* `implement` - Implement\n\* `investigate` - Investigate'
        ),
})

/**
 * Mark a report as opened by the owner.
 */
export const HogsReportsReadCreateBody = /* @__PURE__ */ zod.object({
    report_id: zod.uuid().describe('ID of the report.'),
})

/**
 * Resolve, dismiss or reopen a report.
 */
export const hogsReportsVerdictCreateBodyReasonDefault = ``
export const hogsReportsVerdictCreateBodyReasonMax = 200

export const HogsReportsVerdictCreateBody = /* @__PURE__ */ zod.object({
    report_id: zod.uuid().describe('ID of the report.'),
    status: zod
        .enum(['open', 'resolved', 'dismissed'])
        .describe('\* `open` - Open\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed')
        .describe(
            'resolved or dismissed closes the report. open reopens it.\n\n\* `open` - Open\n\* `resolved` - Resolved\n\* `dismissed` - Dismissed'
        ),
    reason: zod
        .string()
        .max(hogsReportsVerdictCreateBodyReasonMax)
        .default(hogsReportsVerdictCreateBodyReasonDefault)
        .describe('Why, in a few words.'),
})

/**
 * Set the standing rule for one kind of action by this hog.
 */
export const hogsRulesSetCreateBodyKindMax = 60

export const hogsRulesSetCreateBodyKindRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const HogsRulesSetCreateBody = /* @__PURE__ */ zod.object({
    kind: zod
        .string()
        .max(hogsRulesSetCreateBodyKindMax)
        .regex(hogsRulesSetCreateBodyKindRegExp)
        .describe('The action kind the rule covers.'),
    effect: zod
        .enum(['allow', 'ask', 'deny'])
        .describe('\* `allow` - Allow\n\* `ask` - Ask\n\* `deny` - Deny')
        .describe(
            'allow runs without asking, ask waits for the owner, deny refuses.\n\n\* `allow` - Allow\n\* `ask` - Ask\n\* `deny` - Deny'
        ),
})

/**
 * Send a chat message to the owner, as the hog.
 */
export const hogsSayCreateBodyContentMax = 8000

export const HogsSayCreateBody = /* @__PURE__ */ zod.object({
    content: zod.string().max(hogsSayCreateBodyContentMax).describe('The message text.'),
})

/**
 * Schedule a future wake for this hog, once or on a repeat.
 */
export const hogsSchedulesCreateCreateBodyPromptMax = 4000

export const hogsSchedulesCreateCreateBodyCronExpressionMax = 120

export const HogsSchedulesCreateCreateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .string()
        .max(hogsSchedulesCreateCreateBodyPromptMax)
        .describe('A note to your future self: what to check or do when this fires.'),
    run_at: zod.iso.datetime({ offset: true }).nullish().describe('Fire once at this ISO 8601 time.'),
    cron_expression: zod
        .string()
        .max(hogsSchedulesCreateCreateBodyCronExpressionMax)
        .nullish()
        .describe('Fire on a repeat: a 5-field cron expression in UTC, at most every 15 minutes.'),
})

/**
 * Delete one of this hog's schedules.
 */
export const HogsSchedulesDeleteCreateBody = /* @__PURE__ */ zod.object({
    schedule_id: zod.uuid().describe('ID of the schedule to delete.'),
})

/**
 * Send a message to a hog as its owner. The hog wakes and decides whether to reply.
 */
export const hogsSendCreateBodyContentMax = 8000

export const HogsSendCreateBody = /* @__PURE__ */ zod.object({
    content: zod.string().max(hogsSendCreateBodyContentMax).describe('The message text.'),
})

/**
 * Send a note from this hog to another hog, which wakes to read it.
 */
export const hogsTellCreateBodyContentMax = 8000

export const HogsTellCreateBody = /* @__PURE__ */ zod.object({
    to_hog_id: zod.uuid().describe('ID of the hog to send the note to. Find it with hogs-list.'),
    content: zod.string().max(hogsTellCreateBodyContentMax).describe('The note. Say what you found and what you need.'),
})

/**
 * Deliver an event to a trigger. The whole JSON body is the event.
 *
 * Send an `Idempotency-Key` header, or an `id` in the body, so a repeated delivery is dropped.
 */
export const HogsTriggersFireCreateBody = /* @__PURE__ */ zod.record(zod.string(), zod.unknown())

/**
 * Create a trigger: an address that wakes this hog when something posts an event to it.
 */
export const hogsTriggersCreateCreateBodyNameMax = 120

export const hogsTriggersCreateCreateBodyInstructionsDefault = ``
export const hogsTriggersCreateCreateBodyInstructionsMax = 4000

export const HogsTriggersCreateCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogsTriggersCreateCreateBodyNameMax)
        .describe('What sends these events, such as Deploy finished.'),
    instructions: zod
        .string()
        .max(hogsTriggersCreateCreateBodyInstructionsMax)
        .default(hogsTriggersCreateCreateBodyInstructionsDefault)
        .describe('A note to your future self: what to check when an event arrives, and what is worth reporting.'),
})

/**
 * Delete one of this hog's triggers.
 */
export const HogsTriggersDeleteCreateBody = /* @__PURE__ */ zod.object({
    trigger_id: zod.uuid().describe('ID of the trigger to delete.'),
})
