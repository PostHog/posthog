export type AnalyticsEvent =
    | 'mobile_signed_in'
    | 'mobile_create_account_opened'
    | 'mobile_inbox_opened'
    | 'mobile_inbox_report_menu_opened'
    | 'mobile_inbox_report_menu_action'
    | 'mobile_inbox_page_requested'
    | 'mobile_inbox_report_swiped'
    | 'mobile_report_opened'
    | 'mobile_report_chart_scrubbed'
    | 'mobile_chart_point_selected'
    | 'mobile_chart_tooltip_dismissed'
    | 'mobile_chart_range_compared'
    | 'mobile_chart_legend_toggled'
    | 'mobile_report_insight_opened'
    | 'mobile_report_chip_pressed'
    | 'mobile_report_handed_off'
    | 'mobile_handoff_option_changed'
    | 'mobile_decision_answered'
    | 'mobile_report_snoozed'
    | 'mobile_report_resolved'
    | 'mobile_report_dismissed'
    | 'mobile_reviewers_changed'
    | 'mobile_report_priority_changed'
    | 'mobile_report_marked_read'
    | 'mobile_report_marked_unread'
    | 'mobile_chat_option_changed'
    | 'mobile_session_resumed'
    | 'mobile_session_sent'
    | 'mobile_session_stopped'
    | 'mobile_chats_opened'
    | 'mobile_chat_opened'
    | 'mobile_project_picker_opened'
    | 'mobile_project_switched'
    | 'mobile_push_opened'
    | 'mobile_hedgehog_widget_synced'
    | 'mobile_views_opened'
    | 'mobile_view_opened'
    | 'mobile_view_opened_in_web'
    | 'mobile_view_pinned'
    | 'mobile_view_unpinned'
    | 'mobile_pins_reordered'
    | 'mobile_pin_display_changed'
    | 'mobile_pin_tile_chosen'
    | 'mobile_views_refreshed'
    | 'mobile_views_searched'
    | 'mobile_date_range_changed'
    | 'mobile_date_range_compared'
    | 'mobile_chart_point_sheet_opened'
    | 'mobile_chart_about_opened'
    | 'mobile_chart_recordings_opened'
    | 'mobile_chart_people_opened'
    | 'mobile_chart_fullscreen_opened'
    | 'mobile_views_reauth_shown'

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
