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

export const meepTopicsAddContextBodyTextMax = 500

export const meepTopicsAddContextBodyUnitDefault = ``
export const meepTopicsAddContextBodyUnitMax = 40

export const meepTopicsAddContextBodyEffectDefault = `ask`
export const meepTopicsAddContextBodyActionDefault = ``
export const meepTopicsAddContextBodyActionMax = 80

export const MeepTopicsAddContextBody = /* @__PURE__ */ zod.object({
    kind: zod
        .enum(['goal', 'fact', 'rule'])
        .describe('\* `goal` - goal\n\* `fact` - fact\n\* `rule` - rule')
        .describe(
            'What to add: a goal, a fact, or a rule about what you may do.\n\n\* `goal` - goal\n\* `fact` - fact\n\* `rule` - rule'
        ),
    text: zod.string().max(meepTopicsAddContextBodyTextMax).describe('The goal, fact or rule, as one clear sentence.'),
    current: zod.number().optional().describe('Goal only: the latest measured value.'),
    target: zod.number().optional().describe('Goal only: the value to reach or stay under.'),
    unit: zod
        .string()
        .max(meepTopicsAddContextBodyUnitMax)
        .default(meepTopicsAddContextBodyUnitDefault)
        .describe("Goal only: the unit, such as 'per week'."),
    effect: zod
        .enum(['ask', 'allow', 'deny'])
        .describe('\* `ask` - ask\n\* `allow` - allow\n\* `deny` - deny')
        .default(meepTopicsAddContextBodyEffectDefault)
        .describe('Rule only: ask first, allow, or deny.\n\n\* `ask` - ask\n\* `allow` - allow\n\* `deny` - deny'),
    action: zod
        .string()
        .max(meepTopicsAddContextBodyActionMax)
        .default(meepTopicsAddContextBodyActionDefault)
        .describe("Rule only: the kind of action, such as 'feature-flag-change'."),
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
