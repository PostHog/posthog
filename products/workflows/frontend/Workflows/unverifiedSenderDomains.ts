import type { HogFlowApi } from '../generated/api.schemas'

type WithUnverifiedSenders = Partial<Pick<HogFlowApi, 'unverified_email_senders'>>

export function unverifiedSenderDomains(workflow: WithUnverifiedSenders | null | undefined): string[] {
    return [...new Set((workflow?.unverified_email_senders ?? []).map((sender) => sender.domain))]
}
