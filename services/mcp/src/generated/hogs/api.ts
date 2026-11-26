/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 16 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List the hogs you run, newest chat first, with unread counts.
 */
export const HogsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Update a hog. A hog calls this to save its own responsibility, memory or status.
 */
export const hogsPartialUpdatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsPartialUpdateParams = () => zod.object({
    id: zod.string().regex(hogsPartialUpdatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsPartialUpdateBodyNameMax = 80

export const hogsPartialUpdateBodyEmojiMax = 16

export const hogsPartialUpdateBodyColorMax = 16

export const hogsPartialUpdateBodyMemoryMax = 20000

export const HogsPartialUpdateBody = () => zod.object({
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
})

/**
 * List the actions a hog has proposed, newest first, with each one's status.
 */
export const hogsActionsRetrievePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsActionsRetrieveParams = () => zod.object({
    id: zod.string().regex(hogsActionsRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Record that the hog carried out an approved action.
 */
export const hogsActionsDoneCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsActionsDoneCreateParams = () => zod.object({
    id: zod.string().regex(hogsActionsDoneCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsActionsDoneCreateBodyResultMax = 2000

export const HogsActionsDoneCreateBody = () => zod.object({
    action_id: zod.string().describe('ID of the approved action you carried out.'),
    result: zod
        .string()
        .max(hogsActionsDoneCreateBodyResultMax)
        .describe('What happened, with a link when there is one.'),
})

/**
 * Ask to do something outside PostHog. The owner's rules, or the owner, decide.
 */
export const hogsActionsProposeCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsActionsProposeCreateParams = () => zod.object({
    id: zod.string().regex(hogsActionsProposeCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsActionsProposeCreateBodyKindMax = 60

export const hogsActionsProposeCreateBodyKindRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const hogsActionsProposeCreateBodyLabelMax = 200

export const hogsActionsProposeCreateBodyDraftDefault = ``
export const hogsActionsProposeCreateBodyDraftMax = 8000

export const HogsActionsProposeCreateBody = () => zod.object({
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
 * Mark the hog as no longer working.
 */
export const hogsDoneCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsDoneCreateParams = () => zod.object({
    id: zod.string().regex(hogsDoneCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * List the reports a hog has published, open ones first.
 */
export const hogsReportsRetrievePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsReportsRetrieveParams = () => zod.object({
    id: zod.string().regex(hogsReportsRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Publish a report into the owner's chat, as the hog.
 */
export const hogsReportsCreateCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsReportsCreateCreateParams = () => zod.object({
    id: zod.string().regex(hogsReportsCreateCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

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

export const HogsReportsCreateCreateBody = () => zod.object({
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
 * Send a chat message to the owner, as the hog.
 */
export const hogsSayCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsSayCreateParams = () => zod.object({
    id: zod.string().regex(hogsSayCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsSayCreateBodyContentMax = 8000

export const HogsSayCreateBody = () => zod.object({
    content: zod.string().max(hogsSayCreateBodyContentMax).describe('The message text.'),
})

/**
 * List the schedules that will wake this hog.
 */
export const hogsSchedulesRetrievePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsSchedulesRetrieveParams = () => zod.object({
    id: zod.string().regex(hogsSchedulesRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Schedule a future wake for this hog, once or on a repeat.
 */
export const hogsSchedulesCreateCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsSchedulesCreateCreateParams = () => zod.object({
    id: zod.string().regex(hogsSchedulesCreateCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsSchedulesCreateCreateBodyPromptMax = 4000

export const hogsSchedulesCreateCreateBodyCronExpressionMax = 120

export const HogsSchedulesCreateCreateBody = () => zod.object({
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
export const hogsSchedulesDeleteCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsSchedulesDeleteCreateParams = () => zod.object({
    id: zod.string().regex(hogsSchedulesDeleteCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogsSchedulesDeleteCreateBody = () => zod.object({
    schedule_id: zod.string().describe('ID of the schedule to delete.'),
})

/**
 * Send a note from this hog to another hog, which wakes to read it.
 */
export const hogsTellCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsTellCreateParams = () => zod.object({
    id: zod.string().regex(hogsTellCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsTellCreateBodyContentMax = 8000

export const HogsTellCreateBody = () => zod.object({
    to_hog_id: zod.string().describe('ID of the hog to send the note to. Find it with hogs-list.'),
    content: zod.string().max(hogsTellCreateBodyContentMax).describe('The note. Say what you found and what you need.'),
})

/**
 * List the triggers that wake this hog on an outside event.
 */
export const hogsTriggersRetrievePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsTriggersRetrieveParams = () => zod.object({
    id: zod.string().regex(hogsTriggersRetrievePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create a trigger: an address that wakes this hog when something posts an event to it.
 */
export const hogsTriggersCreateCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsTriggersCreateCreateParams = () => zod.object({
    id: zod.string().regex(hogsTriggersCreateCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogsTriggersCreateCreateBodyNameMax = 120

export const hogsTriggersCreateCreateBodyInstructionsDefault = ``
export const hogsTriggersCreateCreateBodyInstructionsMax = 4000

export const HogsTriggersCreateCreateBody = () => zod.object({
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
export const hogsTriggersDeleteCreatePathIdRegExp = new RegExp('^[0-9a-f-]{36}$')

export const HogsTriggersDeleteCreateParams = () => zod.object({
    id: zod.string().regex(hogsTriggersDeleteCreatePathIdRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogsTriggersDeleteCreateBody = () => zod.object({
    trigger_id: zod.string().describe('ID of the trigger to delete.'),
})
