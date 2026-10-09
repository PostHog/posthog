/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 13 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The sizes, models and inference modes that a run can use, with the prices and the limits.
 * @summary Retrieve the cloud agents catalog
 */
export const CloudAgentsCatalogRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The compute cost of a sandbox of one size for a number of minutes. Model usage is not included.
 * @summary Estimate the compute cost of a run
 */
export const CloudAgentsEstimateRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cloudAgentsEstimateRetrieveQueryMinutesMax = 1440

export const CloudAgentsEstimateRetrieveQueryParams = () => zod.object({
    minutes: zod
        .number()
        .min(1)
        .max(cloudAgentsEstimateRetrieveQueryMinutesMax)
        .describe('How many minutes the sandbox is up.'),
    size: zod
        .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
        .describe(
            'Sandbox size to price, as `<vCPU>x<memory in GiB>`.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
        ),
})

/**
 * Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping.
 * @summary List presets
 */
export const CloudAgentsPresetsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CloudAgentsPresetsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * A preset is a named set of run defaults. A run that names a preset needs only a prompt.
 * @summary Create a preset
 */
export const CloudAgentsPresetsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cloudAgentsPresetsCreateBodyRepositoriesItemNameMax = 255

export const cloudAgentsPresetsCreateBodyRepositoriesItemNameRegExp = new RegExp('^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$')
export const cloudAgentsPresetsCreateBodyRepositoriesItemInitialBranchMax = 255

export const cloudAgentsPresetsCreateBodyModelMax = 100

export const cloudAgentsPresetsCreateBodyInstructionsMax = 20000

export const cloudAgentsPresetsCreateBodyIdleMinutesMax = 120

export const cloudAgentsPresetsCreateBodyDescriptionMax = 2000

export const cloudAgentsPresetsCreateBodyTagsItemMax = 50

export const cloudAgentsPresetsCreateBodyTagsMax = 20

export const cloudAgentsPresetsCreateBodyNameMax = 100

export const CloudAgentsPresetsCreateBody = () => zod
    .object({
        repositories: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(cloudAgentsPresetsCreateBodyRepositoriesItemNameMax)
                        .regex(cloudAgentsPresetsCreateBodyRepositoriesItemNameRegExp)
                        .describe('GitHub repository, in the format `owner\/name`.'),
                    initial_branch: zod
                        .string()
                        .max(cloudAgentsPresetsCreateBodyRepositoriesItemInitialBranchMax)
                        .nullish()
                        .describe('Branch that the agent starts from. Null uses the default branch of the repository.'),
                })
            )
            .nullish()
            .describe(
                'Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.'
            ),
        model: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyModelMax)
            .nullish()
            .describe('Default model for the agent. Null lets PostHog select the model.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
            ),
        size: zod
            .union([
                zod
                    .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
                    .describe(
                        '\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
            ),
        inference: zod
            .union([
                zod
                    .enum(['auto', 'own_subscription', 'posthog'])
                    .describe('\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.\n\n\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'
            ),
        instructions: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyInstructionsMax)
            .nullish()
            .describe(
                'Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.'
            ),
        create_pr: zod
            .boolean()
            .nullish()
            .describe('Whether the agent opens a pull request when it finishes. Null uses the product default.'),
        idle_minutes: zod
            .number()
            .min(1)
            .max(cloudAgentsPresetsCreateBodyIdleMinutesMax)
            .nullish()
            .describe(
                'How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.'
            ),
        output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.'
            ),
        description: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyDescriptionMax)
            .optional()
            .describe('What this preset is for.'),
        tags: zod
            .array(zod.string().max(cloudAgentsPresetsCreateBodyTagsItemMax))
            .max(cloudAgentsPresetsCreateBodyTagsMax)
            .optional()
            .describe('Tags added to every run that uses this preset.'),
        name: zod
            .string()
            .max(cloudAgentsPresetsCreateBodyNameMax)
            .describe('Name of the preset. It is unique in the project, without regard to case.'),
    })
    .describe('The run defaults that a preset and the project settings share. A null value sets no default.')

/**
 * Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping.
 * @summary Retrieve a preset
 */
export const CloudAgentsPresetsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The runs of the project, newest first.
 * @summary List runs
 */
export const CloudAgentsRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cloudAgentsRunsListQueryRepositoryMax = 255

export const cloudAgentsRunsListQueryTagMax = 50

export const CloudAgentsRunsListQueryParams = () => zod.object({
    created_after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Return only the runs created at or after this time, in ISO 8601 format.'),
    created_before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Return only the runs created before this time, in ISO 8601 format.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    preset_id: zod.string().optional().describe('Return only the runs that used this preset.'),
    repository: zod
        .string()
        .min(1)
        .max(cloudAgentsRunsListQueryRepositoryMax)
        .optional()
        .describe('Return runs whose repository contains this text.'),
    status: zod
        .enum(['queued', 'running', 'idle', 'done'])
        .optional()
        .describe(
            'Return only the runs with this status. A status filter covers the newest 1,000 runs that are active, for `queued` and `running`, or that have no agent at work, for `idle` and `done`.\n\n\* `queued` - Queued\n\* `running` - Running\n\* `idle` - Idle\n\* `done` - Done'
        ),
    tag: zod
        .string()
        .min(1)
        .max(cloudAgentsRunsListQueryTagMax)
        .optional()
        .describe('Return only the runs that have this tag.'),
})

/**
 * Starts a sandbox with a coding agent that works on the prompt in the repository. The response returns at once with a `queued` run. Read the run or stream its events to follow it. Send the same `Idempotency-Key` header again to get the same run and not a second one.
 * @summary Start a run
 */
export const CloudAgentsRunsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CloudAgentsRunsCreateHeader = () => zod.object({
    'Idempotency-Key': zod
        .string()
        .optional()
        .describe(
            'A key of 1 to 100 characters that is unique for this request. A repeated request with the same key and the same body returns the first run with status 200 and the header `Idempotency-Replayed: true`. The same key with a different body gives status 422.'
        ),
})

export const cloudAgentsRunsCreateBodyRepositoriesItemNameMax = 255

export const cloudAgentsRunsCreateBodyRepositoriesItemNameRegExp = new RegExp('^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$')
export const cloudAgentsRunsCreateBodyRepositoriesItemInitialBranchMax = 255

export const cloudAgentsRunsCreateBodyModelMax = 100

export const cloudAgentsRunsCreateBodyInstructionsMax = 20000

export const cloudAgentsRunsCreateBodyIdleMinutesMax = 120

export const cloudAgentsRunsCreateBodyPromptMax = 64000

export const cloudAgentsRunsCreateBodyPresetMax = 100

export const cloudAgentsRunsCreateBodyTagsItemMax = 50

export const cloudAgentsRunsCreateBodyTagsMax = 20

export const cloudAgentsRunsCreateBodyMetadataMaxOne = 512

export const CloudAgentsRunsCreateBody = () => zod
    .object({
        repositories: zod
            .array(
                zod.object({
                    name: zod
                        .string()
                        .max(cloudAgentsRunsCreateBodyRepositoriesItemNameMax)
                        .regex(cloudAgentsRunsCreateBodyRepositoriesItemNameRegExp)
                        .describe('GitHub repository, in the format `owner\/name`.'),
                    initial_branch: zod
                        .string()
                        .max(cloudAgentsRunsCreateBodyRepositoriesItemInitialBranchMax)
                        .nullish()
                        .describe('Branch that the agent starts from. Null uses the default branch of the repository.'),
                })
            )
            .nullish()
            .describe(
                'The repositories that the agent works in. Only one repository is supported for now. Required unless the preset or the project settings set a default.'
            ),
        model: zod
            .string()
            .max(cloudAgentsRunsCreateBodyModelMax)
            .nullish()
            .describe('Default model for the agent. Null lets PostHog select the model.'),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
                    .describe(
                        '\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'How much the model reasons before it answers. A model supports only some of the values. Null uses the default of the model.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `xhigh` - Extra high\n\* `max` - Max\n\* `ultracode` - Ultracode'
            ),
        size: zod
            .union([
                zod
                    .enum(['1x2', '2x4', '2x8', '4x8', '4x16', '8x16', '8x32', '16x64'])
                    .describe(
                        '\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.\n\n\* `1x2` - 1 vCPU, 2 GiB\n\* `2x4` - 2 vCPU, 4 GiB\n\* `2x8` - 2 vCPU, 8 GiB\n\* `4x8` - 4 vCPU, 8 GiB\n\* `4x16` - 4 vCPU, 16 GiB\n\* `8x16` - 8 vCPU, 16 GiB\n\* `8x32` - 8 vCPU, 32 GiB\n\* `16x64` - 16 vCPU, 64 GiB'
            ),
        inference: zod
            .union([
                zod
                    .enum(['auto', 'own_subscription', 'posthog'])
                    .describe('\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the agent pays for model usage. `auto` uses your own subscription when one is connected for the runtime, and PostHog inference otherwise. Null uses the product default.\n\n\* `auto` - Auto\n\* `own_subscription` - Own Subscription\n\* `posthog` - PostHog'
            ),
        instructions: zod
            .string()
            .max(cloudAgentsRunsCreateBodyInstructionsMax)
            .nullish()
            .describe(
                'Instructions that the agent gets before the prompt. Project instructions come first, then preset instructions, then the instructions of the run.'
            ),
        create_pr: zod
            .boolean()
            .nullish()
            .describe('Whether the agent opens a pull request when it finishes. Null uses the product default.'),
        idle_minutes: zod
            .number()
            .min(1)
            .max(cloudAgentsRunsCreateBodyIdleMinutesMax)
            .nullish()
            .describe(
                'How many minutes the sandbox waits with no activity before it stops, from 1 to 120. The run is then `idle`, and a message continues it. While the agent is in the middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10.'
            ),
        output_schema: zod
            .record(zod.string(), zod.unknown())
            .nullish()
            .describe(
                'A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that matches it, and the run returns the result in `result.output`. Null asks for no structured result.'
            ),
        prompt: zod
            .string()
            .max(cloudAgentsRunsCreateBodyPromptMax)
            .describe('The task for the agent, in plain language.'),
        preset: zod
            .string()
            .max(cloudAgentsRunsCreateBodyPresetMax)
            .nullish()
            .describe(
                'ID or name of the preset whose defaults the run uses. Null uses the default preset of the project, when one is set.'
            ),
        tags: zod
            .array(zod.string().max(cloudAgentsRunsCreateBodyTagsItemMax))
            .max(cloudAgentsRunsCreateBodyTagsMax)
            .optional()
            .describe('Tags for the run. The tags of the preset are added to them.'),
        metadata: zod
            .record(zod.string(), zod.string().max(cloudAgentsRunsCreateBodyMetadataMaxOne))
            .optional()
            .describe(
                'Your own key and value pairs, stored with the run and returned with it. At most 16 pairs. Keys and values are strings.'
            ),
    })
    .describe('The run defaults that a preset and the project settings share. A null value sets no default.')

/**
 * Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping.
 * @summary Retrieve a run
 */
export const CloudAgentsRunsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Asks a `queued` or `running` run to stop. The response has status 202 and the run can still be `running` for a short time. It is then `done` with the reason `cancelled`. An `idle` or `done` run has no agent to stop, so it is returned with status 200 and does not change.
 * @summary Cancel a run
 */
export const CloudAgentsRunsCancelCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * By default, the response is one JSON object with the stored events of all agent sessions. To follow a live run, send `Accept: text/event-stream`. The response is then a Server-Sent Events stream of the current agent session. Its first frame is `event: run` with the ID, the status and the status reason of the run. `Last-Event-ID` and `start=latest` apply to the stream only. To resume after a disconnect, send the `id` of the last event in the `Last-Event-ID` header.
 *
 * **SDK consumers**: a generated fetch wrapper buffers the stream. Use the JSON default through it, and read the stream with a streaming `fetch` or an `EventSource` client.
 * @summary Read the events of a run
 */
export const CloudAgentsRunsEventsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const CloudAgentsRunsEventsRetrieveQueryParams = () => zod.object({
    format: zod
        .enum(['json'])
        .optional()
        .describe('`json` returns the stored events as one JSON object. This is the default.'),
    start: zod
        .enum(['latest'])
        .optional()
        .describe('Applies to the stream only: `latest` skips the stored events and sends only new events.'),
})

export const CloudAgentsRunsEventsRetrieveHeader = () => zod.object({
    'Last-Event-ID': zod
        .string()
        .optional()
        .describe(
            'Applies to the stream only: the `id` of the last event that you received. The stream sends the events after it.'
        ),
})

/**
 * Sends a follow-up message. An agent that is at work gets the message in its current session. An `idle` run starts a new agent session with the message and goes back to `queued`. A `done` run refuses the message with status 409 and the code `run_done`.
 * @summary Send a message to a run
 */
export const CloudAgentsRunsMessagesCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cloudAgentsRunsMessagesCreateBodyContentMax = 64000

export const CloudAgentsRunsMessagesCreateBody = () => zod.object({
    content: zod
        .string()
        .max(cloudAgentsRunsMessagesCreateBodyContentMax)
        .describe('The follow-up message for the agent, in plain language.'),
})

/**
 * The cost of the run up to now, and each sandbox that it used.
 * @summary Retrieve the usage of a run
 */
export const CloudAgentsRunsUsageRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Cost and usage totals of the runs created in a date range, for each day or for each preset.
 * @summary Retrieve cloud agents usage
 */
export const CloudAgentsUsageRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const cloudAgentsUsageRetrieveQueryGroupByDefault = `day`

export const CloudAgentsUsageRetrieveQueryParams = () => zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Start of the range, in ISO 8601 format. The default is 30 days before `date_to`.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('End of the range, not included, in ISO 8601 format. The default is now.'),
    group_by: zod
        .enum(['day', 'preset'])
        .default(cloudAgentsUsageRetrieveQueryGroupByDefault)
        .describe(
            '`day` gives one bucket for each UTC day. `preset` gives one bucket for each preset.\n\n\* `day` - Day\n\* `preset` - Preset'
        ),
})
