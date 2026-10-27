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
 */
export type SlackSetupStepKeyEnumApi = (typeof SlackSetupStepKeyEnumApi)[keyof typeof SlackSetupStepKeyEnumApi]

export const SlackSetupStepKeyEnumApi = {
    AiConsent: 'ai_consent',
    DefaultProject: 'default_project',
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
    /** Setup steps that apply to this install and are not done yet, in display order. ai_consent: the organization must allow AI data processing. default_project: the Slack workspace connects to 2 or more projects and has no default. */
    steps: SlackSetupStepKeyEnumApi[]
    /** Projects connected to this Slack workspace that the person can open. Empty unless default_project is a step. */
    project_options: SlackAppProjectOptionApi[]
}

export interface SlackAppDefaultProjectApi {
    /** ID of the Slack integration of the project that becomes the workspace default. */
    integration_id: number
}
