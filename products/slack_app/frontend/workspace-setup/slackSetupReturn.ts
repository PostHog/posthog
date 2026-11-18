import { urls } from 'scenes/urls'

// pinned: URL search param, the Settings connect button and bookmarks use it
export const SLACK_SETUP_RETURN_PARAM = 'return_to'

export interface SlackSetupReturnLink {
    label: string
    url: string
}

// The URL carries only a key from this list, so the param can't send the person to another site.
const RETURN_TARGETS = {
    settings: (): SlackSetupReturnLink => ({ label: 'Back to settings', url: urls.settings('project-integrations') }),
}

export type SlackSetupReturnTarget = keyof typeof RETURN_TARGETS

export function parseSlackSetupReturnTarget(value: unknown): SlackSetupReturnTarget | undefined {
    return typeof value === 'string' && Object.hasOwn(RETURN_TARGETS, value)
        ? (value as SlackSetupReturnTarget)
        : undefined
}

export function slackSetupReturnLink(target: SlackSetupReturnTarget | undefined): SlackSetupReturnLink | null {
    return target ? RETURN_TARGETS[target]() : null
}
