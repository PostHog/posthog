import { CyclotronJobInputType } from '~/types'

export const SLACK_CHANNEL_TEMPLATE_ID = 'template-slack'
export const SLACK_TEAM_MEMBER_TEMPLATE_ID = 'template-posthog-slack-dm-team-member'

export type SlackRecipientMode = 'channel' | 'team_member'

const TEMPLATE_ID_BY_MODE: Record<SlackRecipientMode, string> = {
    channel: SLACK_CHANNEL_TEMPLATE_ID,
    team_member: SLACK_TEAM_MEMBER_TEMPLATE_ID,
}

// Both templates read these inputs the same way, so they survive a switch. The rest belong to one template only.
const SHARED_INPUT_KEYS = ['slack_workspace', 'text']

/** Which recipient a Slack step sends to, or null when the step is not a Slack step. */
export function slackRecipientMode(templateId: string | undefined): SlackRecipientMode | null {
    if (templateId === SLACK_CHANNEL_TEMPLATE_ID) {
        return 'channel'
    }
    if (templateId === SLACK_TEAM_MEMBER_TEMPLATE_ID) {
        return 'team_member'
    }
    return null
}

/** The step config for the other recipient mode. The input form fills in that template's defaults. */
export function switchSlackRecipientMode(
    inputs: Record<string, CyclotronJobInputType> | undefined,
    mode: SlackRecipientMode
): { template_id: string; inputs: Record<string, CyclotronJobInputType> } {
    const kept = Object.fromEntries(SHARED_INPUT_KEYS.filter((key) => inputs?.[key]).map((key) => [key, inputs![key]]))
    return { template_id: TEMPLATE_ID_BY_MODE[mode], inputs: kept }
}
