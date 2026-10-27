/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
