export type AnalyticsEvent =
    | 'mobile_signed_in'
    | 'mobile_create_account_opened'
    | 'mobile_inbox_opened'
    | 'mobile_inbox_report_menu_opened'
    | 'mobile_inbox_report_menu_action'
    | 'mobile_report_opened'
    | 'mobile_report_chart_scrubbed'
    | 'mobile_report_insight_opened'
    | 'mobile_report_chip_pressed'
    | 'mobile_report_handed_off'
    | 'mobile_decision_answered'
    | 'mobile_report_snoozed'
    | 'mobile_reviewers_changed'
    | 'mobile_report_priority_changed'
    | 'mobile_report_marked_read'
    | 'mobile_chat_sent'
    | 'mobile_chat_resumed'
    | 'mobile_chats_opened'
    | 'mobile_chat_opened'
    | 'mobile_products_opened'
    | 'mobile_project_picker_opened'
    | 'mobile_project_switched'
    | 'mobile_push_opened'

export type AnalyticsProperties = Record<string, string | number | boolean | null | undefined>

export interface AnalyticsClient {
    capture: (event: AnalyticsEvent, properties?: AnalyticsProperties) => void
    identify: (distinctId: string) => void
    /** Starts a new anonymous identity, so the next user on this device is not merged with the last. */
    reset: () => void
}

let client: AnalyticsClient | null = null

/** `src/lib/posthogClient.ts` installs the client at boot when a project key is set. Until then every call is a no-op. */
export function setAnalyticsClient(next: AnalyticsClient | null): void {
    client = next
}

export function track(event: AnalyticsEvent, properties?: AnalyticsProperties): void {
    client?.capture(event, properties)
}

export function identify(distinctId: string): void {
    client?.identify(distinctId)
}

export function resetAnalytics(): void {
    client?.reset()
}
