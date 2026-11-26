/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const MeepTopicsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MeepTopicsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const MeepTopicsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MeepTopicsAddContextParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsAddContextBodyTextMax = 500

export const meepTopicsAddContextBodyUnitDefault = ``
export const meepTopicsAddContextBodyUnitMax = 40

export const meepTopicsAddContextBodyEffectDefault = `ask`
export const meepTopicsAddContextBodyActionDefault = ``
export const meepTopicsAddContextBodyActionMax = 80

export const MeepTopicsAddContextBody = () => zod.object({
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

export const MeepTopicsBindRoutineParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsBindRoutineBodyNameMax = 100

export const meepTopicsBindRoutineBodyTriggerMax = 200

export const MeepTopicsBindRoutineBody = () => zod.object({
    workflow_id: zod.string().describe('The ID of the PostHog workflow this topic should show as a routine.'),
    name: zod
        .string()
        .max(meepTopicsBindRoutineBodyNameMax)
        .describe("A short name for the routine, shown in the topic's Routines."),
    trigger: zod
        .string()
        .max(meepTopicsBindRoutineBodyTriggerMax)
        .describe("When the routine runs, in plain words, for example 'Every day at 09:00 UTC'."),
})

export const MeepTopicsSetScoutEnabledParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MeepTopicsSetScoutEnabledBody = () => zod.object({
    scout_id: zod.string(),
    enabled: zod.boolean(),
})

export const MeepTopicsCreateScoutParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsCreateScoutBodyNameMax = 100

export const meepTopicsCreateScoutBodyInstructionsMax = 16000

export const meepTopicsCreateScoutBodyCronMax = 100

export const MeepTopicsCreateScoutBody = () => zod.object({
    name: zod.string().max(meepTopicsCreateScoutBodyNameMax),
    instructions: zod.string().max(meepTopicsCreateScoutBodyInstructionsMax),
    cron: zod
        .string()
        .max(meepTopicsCreateScoutBodyCronMax)
        .optional()
        .describe("Optional five-field schedule in the project's timezone. Defaults to the native scout cadence."),
})

export const MeepTopicsAnswerTaskParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsAnswerTaskBodyAnswerMax = 16000

export const MeepTopicsAnswerTaskBody = () => zod.object({
    request_id: zod.string().describe('A stable ID for this answer, reused when retrying.'),
    item_id: zod.string().describe('The board item asking for input.'),
    question_run_id: zod.string().describe('The run ID that asked the question.'),
    answer: zod.string().max(meepTopicsAnswerTaskBodyAnswerMax).describe("The person's answer to the child task."),
})

export const MeepTopicsStartTaskParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsStartTaskBodyTitleMax = 255

export const meepTopicsStartTaskBodyBriefMax = 16000

export const MeepTopicsStartTaskBody = () => zod.object({
    request_id: zod.string().describe('A stable ID for this request, reused when retrying.'),
    title: zod.string().max(meepTopicsStartTaskBodyTitleMax).describe('A short title for the board task.'),
    brief: zod.string().max(meepTopicsStartTaskBodyBriefMax).describe('The independent work and expected result.'),
})

export const MeepTopicsWaitTasksParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const meepTopicsWaitTasksBodyItemIdsMax = 20

export const MeepTopicsWaitTasksBody = () => zod.object({
    request_id: zod.string().describe('A stable ID for this wait, reused when retrying.'),
    item_ids: zod
        .array(zod.string())
        .max(meepTopicsWaitTasksBodyItemIdsMax)
        .describe('Up to 20 board item IDs to wait for.'),
})
