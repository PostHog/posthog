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
 * Today's personal briefing: a short text about the top 5 items and a left bar with the top 10. There are two editions a day, from 8:00 and from 12:00 local time. Starts generating the current edition when there is none yet; while it writes, the template draft is returned with status 'writing'.
 * @summary Get today's briefing
 */
export const TodayBriefingRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const todayBriefingRetrieveQueryTimezoneMax = 64

export const TodayBriefingRetrieveQueryParams = () => zod.object({
    timezone: zod
        .string()
        .max(todayBriefingRetrieveQueryTimezoneMax)
        .optional()
        .describe(
            "IANA timezone of the person's browser, for example Europe\/Prague. Editions start at 8:00 and 12:00 in it. Defaults to the project timezone."
        ),
})

/**
 * Store the text and the items of a briefing that is being generated for the current user. Only the briefing named in the generation prompt can be written. The text must link every item exactly once, highlight only the first item, keep labels to 6 words and signals to 40 characters, and use no em or en dashes; a 400 lists every rule the text broke so it can be fixed and sent again.
 * @summary Write today's briefing
 */
export const TodayBriefingWriteCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const todayBriefingWriteCreateBodyItemsItemUrgencyMin = 0
export const todayBriefingWriteCreateBodyItemsItemUrgencyMax = 3

export const TodayBriefingWriteCreateBody = () => zod.object({
    briefing_id: zod.string().describe('The briefing to write, from the prompt that started the run.'),
    headline: zod
        .string()
        .describe("One sentence that counts the items, for example 'Five items need your attention'."),
    paragraphs: zod
        .array(
            zod.array(
                zod.object({
                    text: zod.string().describe('A run of text in a paragraph. Includes its own spaces.'),
                    item_key: zod
                        .string()
                        .nullable()
                        .describe('Key of the item this run links to, or null for plain text.'),
                    highlight: zod.boolean().describe('True only for the run that names the top item.'),
                })
            )
        )
        .describe(
            'Two or three short paragraphs, each a list of segments. A segment with an item_key links that item; every item is linked exactly once and only the first item has highlight true.'
        ),
    items: zod
        .array(
            zod.object({
                key: zod
                    .string()
                    .describe(
                        'Stable item key: report:<uuid>, dashboard:<id>, insight:<short_id>, alert:<id>, ticket:<uuid>, issue:<uuid> or github_pr:<owner\/repo>#<number>.'
                    ),
                title: zod.string().describe("The item's own title, as its source names it."),
                label: zod.string().describe('Left-bar label of at most 6 words that says what the item is.'),
                signal: zod
                    .string()
                    .describe('Short fact under the label, at most 40 characters, with a number when there is one.'),
                url: zod
                    .string()
                    .describe(
                        'Where the item opens: an app path such as \/project\/1\/inbox\/<uuid>, or a GitHub URL.'
                    ),
                urgency: zod
                    .number()
                    .min(todayBriefingWriteCreateBodyItemsItemUrgencyMin)
                    .max(todayBriefingWriteCreateBodyItemsItemUrgencyMax)
                    .describe('0 act now, 1 today, 2 this week, 3 when the person has time.'),
                facts: zod
                    .array(
                        zod.object({
                            name: zod.string().describe('Fact name, for example pct_change or unread_messages.'),
                            value: zod.string().describe('Fact value as text.'),
                        })
                    )
                    .describe('The numbers and short facts the text uses for this item, so a reader can check them.'),
                source_product: zod
                    .string()
                    .nullish()
                    .describe(
                        'For a report, the product its signals came from, for example error_tracking or session_replay.'
                    ),
                group: zod
                    .enum(['report', 'dashboard', 'other'])
                    .describe('\* `report` - REPORT\n\* `dashboard` - DASHBOARD\n\* `other` - OTHER'),
                source: zod
                    .enum(['self_driving', 'product_analytics', 'alerts', 'support', 'error_tracking', 'github'])
                    .describe(
                        '\* `self_driving` - SELF_DRIVING\n\* `product_analytics` - PRODUCT_ANALYTICS\n\* `alerts` - ALERTS\n\* `support` - SUPPORT\n\* `error_tracking` - ERROR_TRACKING\n\* `github` - GITHUB'
                    ),
                reason: zod
                    .enum([
                        'claimed_by_you',
                        'waiting_for_you',
                        'suggested_reviewer',
                        'urgent_for_project',
                        'dashboard_you_viewed',
                        'dashboard_you_starred',
                        'insight_you_viewed',
                        'insight_you_starred',
                        'alert_firing',
                        'assigned_ticket',
                        'assigned_error_issue',
                        'review_requested',
                        'your_pull_request',
                    ])
                    .describe(
                        '\* `claimed_by_you` - CLAIMED_BY_YOU\n\* `waiting_for_you` - WAITING_FOR_YOU\n\* `suggested_reviewer` - SUGGESTED_REVIEWER\n\* `urgent_for_project` - URGENT_FOR_PROJECT\n\* `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED\n\* `dashboard_you_starred` - DASHBOARD_YOU_STARRED\n\* `insight_you_viewed` - INSIGHT_YOU_VIEWED\n\* `insight_you_starred` - INSIGHT_YOU_STARRED\n\* `alert_firing` - ALERT_FIRING\n\* `assigned_ticket` - ASSIGNED_TICKET\n\* `assigned_error_issue` - ASSIGNED_ERROR_ISSUE\n\* `review_requested` - REVIEW_REQUESTED\n\* `your_pull_request` - YOUR_PULL_REQUEST'
                    ),
            })
        )
        .describe('The items the text names, most urgent first, at most 5. Each needs its own sentence.'),
})

/**
 * The ranked items behind today's briefing, with the facts and the reason for each, without the written text.
 * @summary List today's ranked items
 */
export const TodayCandidatesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const todayCandidatesRetrieveQueryTimezoneMax = 64

export const TodayCandidatesRetrieveQueryParams = () => zod.object({
    timezone: zod
        .string()
        .max(todayCandidatesRetrieveQueryTimezoneMax)
        .optional()
        .describe(
            "IANA timezone of the person's browser, for example Europe\/Prague. Editions start at 8:00 and 12:00 in it. Defaults to the project timezone."
        ),
})
