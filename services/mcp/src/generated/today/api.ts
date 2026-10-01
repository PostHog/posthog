/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Today's personal briefing: a short text about up to 5 items and the same items for the left bar. There are two editions a day, from 8:00 and from 12:00 local time. Starts generating the current edition when there is none yet and returns it as 'collecting'. While a newer edition is being written, the day's last ready briefing is returned as 'writing', so it can stay on screen; poll again after a few seconds.
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
 * The items behind today's briefing, with the facts and the reason for each, without the written text.
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
