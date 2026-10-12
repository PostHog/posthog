export const MAX_SHARED_EMAILS = 10

const SLACK_MESSAGE_LINK = /^https:\/\/([a-z0-9-]+\.)*slack\.com\/archives\/[A-Z0-9]+\/p\d{7,}/

export interface ShareFormState {
    integrationId: number | null
    channel: string | null
    threadLink: string
    selectedEmailCount: number
    canUploadImages: boolean
}

export function isSlackMessageLink(link: string): boolean {
    return SLACK_MESSAGE_LINK.test(link.trim())
}

export function getShareDisabledReason(form: ShareFormState): string | undefined {
    const threadLink = form.threadLink.trim()
    if (!form.integrationId) {
        return 'Select a Slack workspace'
    }
    if (!form.channel && !threadLink) {
        return 'Select a channel or paste a thread link'
    }
    if (threadLink && !isSlackMessageLink(threadLink)) {
        return 'Paste a link to a Slack message, copied with Copy link'
    }
    if (form.selectedEmailCount > MAX_SHARED_EMAILS) {
        return `Select at most ${MAX_SHARED_EMAILS} emails`
    }
    if (form.selectedEmailCount > 0 && !form.canUploadImages) {
        return 'Reconnect Slack to share the emails, or deselect them'
    }
    return undefined
}
