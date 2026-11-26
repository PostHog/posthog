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

export const meepTopicsCreateBodyTitleMax = 255

export const MeepTopicsCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().max(meepTopicsCreateBodyTitleMax),
    mission: zod.string(),
})

export const MeepTopicsConversationCreateBody = /* @__PURE__ */ zod.object({
    task_id: zod.uuid(),
})

export const meepTopicsBindRoutineBodyNameMax = 100

export const meepTopicsBindRoutineBodyTriggerMax = 200

export const MeepTopicsBindRoutineBody = /* @__PURE__ */ zod.object({
    workflow_id: zod.uuid().describe('The ID of the PostHog workflow this topic should show as a routine.'),
    name: zod
        .string()
        .max(meepTopicsBindRoutineBodyNameMax)
        .describe("A short name for the routine, shown in the topic's Routines."),
    trigger: zod
        .string()
        .max(meepTopicsBindRoutineBodyTriggerMax)
        .describe("When the routine runs, in plain words, for example 'Every day at 09:00 UTC'."),
})

export const MeepTopicsSetScoutEnabledBody = /* @__PURE__ */ zod.object({
    scout_id: zod.uuid(),
    enabled: zod.boolean(),
})

export const meepTopicsCreateScoutBodyNameMax = 100

export const meepTopicsCreateScoutBodyInstructionsMax = 16000

export const meepTopicsCreateScoutBodyCronMax = 100

export const MeepTopicsCreateScoutBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(meepTopicsCreateScoutBodyNameMax),
    instructions: zod.string().max(meepTopicsCreateScoutBodyInstructionsMax),
    cron: zod
        .string()
        .max(meepTopicsCreateScoutBodyCronMax)
        .optional()
        .describe("Optional five-field schedule in the project's timezone. Defaults to the native scout cadence."),
})

export const meepTopicsAnswerTaskBodyAnswerMax = 16000

export const MeepTopicsAnswerTaskBody = /* @__PURE__ */ zod.object({
    request_id: zod.uuid().describe('A stable ID for this answer, reused when retrying.'),
    item_id: zod.uuid().describe('The board item asking for input.'),
    question_run_id: zod.uuid().describe('The run ID that asked the question.'),
    answer: zod.string().max(meepTopicsAnswerTaskBodyAnswerMax).describe("The person's answer to the child task."),
})

export const meepTopicsStartTaskBodyTitleMax = 255

export const meepTopicsStartTaskBodyBriefMax = 16000

export const MeepTopicsStartTaskBody = /* @__PURE__ */ zod.object({
    request_id: zod.uuid().describe('A stable ID for this request, reused when retrying.'),
    title: zod.string().max(meepTopicsStartTaskBodyTitleMax).describe('A short title for the board task.'),
    brief: zod.string().max(meepTopicsStartTaskBodyBriefMax).describe('The independent work and expected result.'),
})

export const meepTopicsWaitTasksBodyItemIdsMax = 20

export const MeepTopicsWaitTasksBody = /* @__PURE__ */ zod.object({
    request_id: zod.uuid().describe('A stable ID for this wait, reused when retrying.'),
    item_ids: zod
        .array(zod.uuid())
        .max(meepTopicsWaitTasksBodyItemIdsMax)
        .describe('Up to 20 board item IDs to wait for.'),
})
