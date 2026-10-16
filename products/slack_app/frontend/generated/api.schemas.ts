/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
    /** Keys of the setup steps that apply to this install and are not done yet, in display order. */
    steps: string[]
}
