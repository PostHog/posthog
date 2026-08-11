import type { LemonButtonProps } from '@posthog/lemon-ui'

/**
 * Button props that surface a failed chat-task kickoff, so the CTA shows a persistent retry state
 * rather than relying on a toast that fades. Shared by the "Suggest a scout" button and the
 * fleet-overview chips so their retry tone and copy can't drift apart.
 */
export function scoutChatRetryButtonProps(
    failedChatPrompt: string | null,
    prompt: string
): { failed: boolean; status: LemonButtonProps['status']; tooltip: string | undefined } {
    const failed = failedChatPrompt === prompt
    return {
        failed,
        status: failed ? 'danger' : undefined,
        tooltip: failed ? "Couldn't start the task. Click to try again." : undefined,
    }
}
