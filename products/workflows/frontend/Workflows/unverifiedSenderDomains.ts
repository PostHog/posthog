import type { HogFlow } from './hogflows/types'

export function unverifiedSenderDomains(workflow: HogFlow | null | undefined): string[] {
    return [...new Set((workflow?.unverified_email_senders ?? []).map((sender) => sender.domain))]
}
