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
 * @summary Replace the settings of one channel of a Slack app install
 */
export const slackAppSettingsChannelsUpdateBodyDefaultRepositoryMax = 255

export const SlackAppSettingsChannelsUpdateBody = /* @__PURE__ */ zod.object({
    default_integration_id: zod
        .number()
        .nullable()
        .describe('ID of the Slack integration of a project connected to this workspace. Null inherits.'),
    default_repository: zod
        .string()
        .max(slackAppSettingsChannelsUpdateBodyDefaultRepositoryMax)
        .nullable()
        .describe('Repository as owner\/name. Null inherits.'),
    untagged_question_mode: zod
        .union([
            zod
                .enum(['ask', 'never'])
                .describe('\* `ask` - Asks before answering\n\* `never` - Only answers @-mentions'),
            zod.null(),
        ])
        .describe(
            "What PostHog does with top-level questions in this channel that do not tag it. Null uses each person's mode. A channel only makes it stricter.\n\n\* `ask` - Asks before answering\n\* `never` - Only answers @-mentions"
        ),
})

/**
 * @summary Change your own settings for a Slack app install
 */
export const slackAppSettingsPersonalPartialUpdateBodyReactionsOneWorkingOneEmojiMax = 102

export const slackAppSettingsPersonalPartialUpdateBodyReactionsOneDoneOneEmojiMax = 102

export const slackAppSettingsPersonalPartialUpdateBodyReactionsOneErrorOneEmojiMax = 102

export const slackAppSettingsPersonalPartialUpdateBodyReactionsOnePoliteOneEmojiMax = 102

export const SlackAppSettingsPersonalPartialUpdateBody = /* @__PURE__ */ zod.object({
    reactions: zod
        .object({
            working: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsPersonalPartialUpdateBodyReactionsOneWorkingOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added to a message when PostHog starts on the request.'),
            done: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsPersonalPartialUpdateBodyReactionsOneDoneOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added when PostHog replies. The working reaction is removed.'),
            error: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsPersonalPartialUpdateBodyReactionsOneErrorOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added when the request fails.'),
            polite: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsPersonalPartialUpdateBodyReactionsOnePoliteOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added after PostHog replies to a message that says please or thanks.'),
        })
        .optional()
        .describe("Replaces this person's reaction choices. A reaction left out inherits the workspace choice."),
    default_integration_id: zod
        .number()
        .nullish()
        .describe(
            "ID of the Slack integration of the project this person's mentions route to. Null uses the workspace default."
        ),
    untagged_followup_mode: zod
        .union([
            zod
                .enum(['auto', 'ask', 'never'])
                .describe('\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer'),
            zod.null(),
        ])
        .optional()
        .describe(
            'What PostHog does with untagged replies in threads this person started. Null uses the workspace default.\n\n\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer'
        ),
    untagged_question_mode: zod
        .union([
            zod
                .enum(['auto', 'ask', 'never'])
                .describe('\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer'),
            zod.null(),
        ])
        .optional()
        .describe(
            "What PostHog does with this person's top-level channel questions that do not tag it. Null uses the workspace default.\n\n\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer"
        ),
    thread_join_mode: zod
        .union([
            zod
                .enum(['never', 'ask_per_person', 'ask_per_thread', 'allow'])
                .describe(
                    '\* `never` - Ignore others\n\* `ask_per_person` - Ask for each person\n\* `ask_per_thread` - Ask once for each thread\n\* `allow` - Allow anyone'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'What PostHog does when someone else tags it in a thread this person started. Null uses the workspace default.\n\n\* `never` - Ignore others\n\* `ask_per_person` - Ask for each person\n\* `ask_per_thread` - Ask once for each thread\n\* `allow` - Allow anyone'
        ),
    auto_model_choice: zod
        .boolean()
        .optional()
        .describe('Whether PostHog picks the model for each task this person starts from Slack.'),
    feature_tips_enabled: zod
        .boolean()
        .optional()
        .describe('Whether PostHog sends this person short tips about Slack app features.'),
    chatgpt_apps_mode: zod
        .enum(['off', 'until_join', 'always'])
        .describe(
            '\* `off` - Apps off\n\* `until_join` - Apps on until someone else joins\n\* `always` - Apps always on'
        )
        .optional()
        .describe(
            "Whether Slack tasks on this person's ChatGPT plan can use the apps connected to that plan: off, on until someone else joins the thread, or always on. Applies to tasks started after the change.\n\n\* `off` - Apps off\n\* `until_join` - Apps on until someone else joins\n\* `always` - Apps always on"
        ),
})

/**
 * @summary Change the workspace settings of a Slack app install
 */
export const slackAppSettingsWorkspacePartialUpdateBodyReactionsOneWorkingOneEmojiMax = 102

export const slackAppSettingsWorkspacePartialUpdateBodyReactionsOneDoneOneEmojiMax = 102

export const slackAppSettingsWorkspacePartialUpdateBodyReactionsOneErrorOneEmojiMax = 102

export const slackAppSettingsWorkspacePartialUpdateBodyReactionsOnePoliteOneEmojiMax = 102

export const SlackAppSettingsWorkspacePartialUpdateBody = /* @__PURE__ */ zod.object({
    reactions: zod
        .object({
            working: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsWorkspacePartialUpdateBodyReactionsOneWorkingOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added to a message when PostHog starts on the request.'),
            done: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsWorkspacePartialUpdateBodyReactionsOneDoneOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added when PostHog replies. The working reaction is removed.'),
            error: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsWorkspacePartialUpdateBodyReactionsOneErrorOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added when the request fails.'),
            polite: zod
                .object({
                    emoji: zod
                        .string()
                        .max(slackAppSettingsWorkspacePartialUpdateBodyReactionsOnePoliteOneEmojiMax)
                        .nullish()
                        .describe(
                            'Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.'
                        ),
                    enabled: zod.boolean().nullish().describe('Whether PostHog adds this reaction. Null inherits.'),
                })
                .optional()
                .describe('Added after PostHog replies to a message that says please or thanks.'),
        })
        .optional()
        .describe("Replaces the workspace's reaction choices. A reaction left out inherits PostHog's default."),
    external_channels_enabled: zod
        .boolean()
        .optional()
        .describe('Whether PostHog works in Slack channels shared with other organizations.'),
    default_integration_id: zod
        .number()
        .nullish()
        .describe("ID of the Slack integration of the workspace's default project. Null removes the default."),
    channel_welcome_mode: zod
        .union([
            zod
                .enum(['channel', 'inviter', 'off'])
                .describe(
                    '\* `channel` - Post in the channel\n\* `inviter` - Only the person who added the app\n\* `off` - No greeting'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Where PostHog sends its greeting when someone adds the app to a channel. Null restores posting in the channel.\n\n\* `channel` - Post in the channel\n\* `inviter` - Only the person who added the app\n\* `off` - No greeting'
        ),
    untagged_followup_mode: zod
        .union([
            zod
                .enum(['auto', 'ask', 'never'])
                .describe('\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer'),
            zod.null(),
        ])
        .optional()
        .describe(
            "The default for untagged replies in a person's threads. Null uses PostHog's default.\n\n\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer"
        ),
    untagged_question_mode: zod
        .union([
            zod
                .enum(['auto', 'ask', 'never'])
                .describe('\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer'),
            zod.null(),
        ])
        .optional()
        .describe(
            "The default for a person's untagged channel questions. Null uses PostHog's default.\n\n\* `auto` - Answer automatically\n\* `ask` - Ask first\n\* `never` - Never answer"
        ),
    thread_join_mode: zod
        .union([
            zod
                .enum(['never', 'ask_per_person', 'ask_per_thread', 'allow'])
                .describe(
                    '\* `never` - Ignore others\n\* `ask_per_person` - Ask for each person\n\* `ask_per_thread` - Ask once for each thread\n\* `allow` - Allow anyone'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            "The default for others tagging PostHog in a person's thread. Null uses PostHog's default.\n\n\* `never` - Ignore others\n\* `ask_per_person` - Ask for each person\n\* `ask_per_thread` - Ask once for each thread\n\* `allow` - Allow anyone"
        ),
})

/**
 * @summary Set the default project for the Slack workspace of a Slack app install
 */
export const SlackAppWorkspaceSetupDefaultProjectCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod
        .number()
        .describe('ID of the Slack integration of the project that becomes the workspace default.'),
})

/**
 * @summary Add PostHog to public channels of a Slack app install
 */
export const slackAppWorkspaceSetupJoinChannelsCreateBodyChannelIdsMax = 20

export const slackAppWorkspaceSetupJoinChannelsCreateBodyPostWelcomeDefault = true

export const SlackAppWorkspaceSetupJoinChannelsCreateBody = /* @__PURE__ */ zod.object({
    channel_ids: zod
        .array(zod.string())
        .min(1)
        .max(slackAppWorkspaceSetupJoinChannelsCreateBodyChannelIdsMax)
        .describe('IDs of the public channels that PostHog joins.'),
    post_welcome: zod
        .boolean()
        .default(slackAppWorkspaceSetupJoinChannelsCreateBodyPostWelcomeDefault)
        .describe('Whether PostHog posts its welcome message in each channel it joins. When false, it joins quietly.'),
})
