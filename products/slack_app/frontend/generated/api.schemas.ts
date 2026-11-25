/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface SlackAppReactionChoiceApi {
    /**
     * Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.
     * @maxLength 102
     * @nullable
     */
    emoji?: string | null
    /**
     * Whether PostHog adds this reaction. Null inherits.
     * @nullable
     */
    enabled?: boolean | null
}

export interface SlackAppReactionChoicesApi {
    /** Added to a message when PostHog starts on the request. */
    working?: SlackAppReactionChoiceApi
    /** Added when PostHog replies. The working reaction is removed. */
    done?: SlackAppReactionChoiceApi
    /** Added when the request fails. */
    error?: SlackAppReactionChoiceApi
    /** Added after PostHog replies to a message that says please or thanks. */
    polite?: SlackAppReactionChoiceApi
}

export interface SlackAppWorkspaceSettingsApi {
    /** The workspace's reaction choices. Null fields use PostHog's defaults. */
    reactions: SlackAppReactionChoicesApi
    /** Whether PostHog works in Slack channels shared with other organizations. */
    external_channels_enabled: boolean
}

export interface SlackAppResolvedReactionApi {
    /** Slack emoji name that PostHog uses. */
    emoji: string
    /** Whether PostHog adds this reaction. */
    enabled: boolean
}

export interface SlackAppResolvedReactionsApi {
    /** The reaction when PostHog starts on a request. */
    working: SlackAppResolvedReactionApi
    /** The reaction when PostHog replies. */
    done: SlackAppResolvedReactionApi
    /** The reaction when the request fails. */
    error: SlackAppResolvedReactionApi
    /** The reaction to a message that says please or thanks. */
    polite: SlackAppResolvedReactionApi
}

export interface SlackAppPersonalSettingsApi {
    /**
     * The Slack user this person linked in this workspace. Null when they have not linked one.
     * @nullable
     */
    slack_user_id: string | null
    /** This person's reaction choices. Null fields use the workspace choice. */
    reactions: SlackAppReactionChoicesApi
    /** The reactions PostHog adds to this person's messages, after the workspace and default fallbacks. */
    effective_reactions: SlackAppResolvedReactionsApi
}

export interface SlackAppSettingsApi {
    /** ID of the Slack integration that these settings are for. */
    integration_id: number
    /**
     * Name of the Slack workspace, as Slack sent it at install time.
     * @nullable
     */
    slack_workspace_name: string | null
    /** Whether this person can change workspace settings: the person who installed Slack, or a project admin. */
    can_edit_workspace: boolean
    /** Settings for everyone in the Slack workspace. */
    workspace: SlackAppWorkspaceSettingsApi
    /** Settings for this person's own Slack messages. */
    personal: SlackAppPersonalSettingsApi
}

/**
 * * `auto` - Always pick it up
 * * `ask` - Ask before picking it up
 * * `never` - Never pick it up
 */
export type UntaggedFollowupModeEnumApi = (typeof UntaggedFollowupModeEnumApi)[keyof typeof UntaggedFollowupModeEnumApi]

export const UntaggedFollowupModeEnumApi = {
    Auto: 'auto',
    Ask: 'ask',
    Never: 'never',
} as const

export interface SlackAppChannelSettingsApi {
    /** Slack channel ID. */
    slack_channel_id: string
    /**
     * ID of the Slack integration of the project that mentions in this channel route to. Null inherits.
     * @nullable
     */
    default_integration_id: number | null
    /**
     * Repository, as owner/name, that tasks started in this channel use. Null inherits.
     * @nullable
     */
    default_repository: string | null
    /** What PostHog does with top-level questions in this channel that do not tag it. Null inherits.
     *
     * * `auto` - Always pick it up
     * * `ask` - Ask before picking it up
     * * `never` - Never pick it up */
    untagged_question_mode: UntaggedFollowupModeEnumApi | null
    /**
     * Name of the person who last changed this channel's settings.
     * @nullable
     */
    updated_by_name: string | null
    /**
     * When this channel's settings last changed.
     * @nullable
     */
    updated_at: string | null
}

export interface SlackAppChannelSettingsListApi {
    /** Channels that have at least one setting. */
    channels: SlackAppChannelSettingsApi[]
}

export interface SlackAppChannelSettingsUpdateApi {
    /**
     * ID of the Slack integration of a project connected to this workspace. Null inherits.
     * @nullable
     */
    default_integration_id: number | null
    /**
     * Repository as owner/name. Null inherits.
     * @maxLength 255
     * @nullable
     */
    default_repository: string | null
    /** What PostHog does with top-level questions in this channel that do not tag it. Null inherits.
     *
     * * `auto` - Always pick it up
     * * `ask` - Ask before picking it up
     * * `never` - Never pick it up */
    untagged_question_mode: UntaggedFollowupModeEnumApi | null
}

export interface PatchedSlackAppPersonalSettingsUpdateApi {
    /** Replaces this person's reaction choices. A reaction left out inherits the workspace choice. */
    reactions?: SlackAppReactionChoicesApi
}

export interface PatchedSlackAppWorkspaceSettingsUpdateApi {
    /** Replaces the workspace's reaction choices. A reaction left out inherits PostHog's default. */
    reactions?: SlackAppReactionChoicesApi
    /** Whether PostHog works in Slack channels shared with other organizations. */
    external_channels_enabled?: boolean
}

/**
 * * `ai_consent` - AI data processing
 * * `default_project` - Default project
 * * `channels` - Channels
 */
export type SlackSetupStepKeyEnumApi = (typeof SlackSetupStepKeyEnumApi)[keyof typeof SlackSetupStepKeyEnumApi]

export const SlackSetupStepKeyEnumApi = {
    AiConsent: 'ai_consent',
    DefaultProject: 'default_project',
    Channels: 'channels',
} as const

export interface SlackAppProjectOptionApi {
    /** ID of the Slack integration that connects this project. */
    integration_id: number
    /** Name of the PostHog project. */
    project_name: string
    /** Name of the organization that owns the project. */
    organization_name: string
}

export interface SlackAppWorkspaceSetupApi {
    /** ID of the Slack integration that this setup is for. */
    integration_id: number
    /**
     * Name of the Slack workspace, as Slack sent it at install time.
     * @nullable
     */
    slack_workspace_name: string | null
    /**
     * Link that opens the PostHog app's direct message in this Slack workspace. Null when the install has no app ID.
     * @nullable
     */
    open_slack_url: string | null
    /** Setup steps that apply to this install and are not done yet, in display order. ai_consent: the organization must allow AI data processing. default_project: the Slack workspace connects to 2 or more projects and has no default. channels: the install can join channels, and the setup started on the Slack page. */
    steps: SlackSetupStepKeyEnumApi[]
    /** Projects connected to this Slack workspace that the person can open. Empty unless default_project is a step. */
    project_options: SlackAppProjectOptionApi[]
    /** Whether a channel join from this setup can post the welcome message in the channel. False when channels is not a step, or when the workspace sends the welcome only to the inviter or turns it off. */
    can_post_channel_welcome: boolean
}

export interface SlackAppChannelOptionApi {
    /** Slack channel ID. */
    id: string
    /** Channel name, without the leading #. */
    name: string
    /** Whether PostHog is already in the channel. */
    is_member: boolean
}

export interface SlackAppChannelOptionsApi {
    /** Public channels that PostHog can join. Shared channels are left out. */
    channels: SlackAppChannelOptionApi[]
}

export interface SlackAppDefaultProjectApi {
    /** ID of the Slack integration of the project that becomes the workspace default. */
    integration_id: number
}

export interface SlackAppJoinChannelsApi {
    /**
     * IDs of the public channels that PostHog joins.
     * @minItems 1
     * @maxItems 20
     */
    channel_ids: string[]
    /** Whether PostHog posts its welcome message in each channel it joins. When false, it joins quietly. */
    post_welcome?: boolean
}

export interface SlackAppChannelJoinResultApi {
    /** Slack channel ID. */
    channel_id: string
    /**
     * Slack's error code when PostHog could not join, or null when it joined.
     * @nullable
     */
    error: string | null
}

export interface SlackAppJoinChannelsResultApi {
    /** The result for each channel, in request order. */
    results: SlackAppChannelJoinResultApi[]
}

export type SlackAppWorkspaceSetupRetrieveParams = {
    /**
     * Where the Slack install started. slack_page adds the steps for a person who sets up Slack on purpose.
     *
     * * `slack_page` - The Slack page in PostHog
     * * `other` - Another place, such as a channel picker
     * @minLength 1
     */
    entry?: SlackAppWorkspaceSetupRetrieveEntry
}

export type SlackAppWorkspaceSetupRetrieveEntry =
    (typeof SlackAppWorkspaceSetupRetrieveEntry)[keyof typeof SlackAppWorkspaceSetupRetrieveEntry]

export const SlackAppWorkspaceSetupRetrieveEntry = {
    SlackPage: 'slack_page',
    Other: 'other',
} as const
