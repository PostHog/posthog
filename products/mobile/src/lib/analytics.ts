export type AnalyticsEvent =
    | 'mobile_signed_in'
    | 'mobile_sign_in_started'
    | 'mobile_sign_in_failed'
    | 'mobile_sign_in_region_changed'
    | 'mobile_session_restored'
    | 'mobile_signed_out'
    | 'mobile_account_reload_failed'
    | 'mobile_sign_out_confirm_shown'
    | 'mobile_sign_out_cancelled'
    | 'mobile_demo_started'
    | 'mobile_demo_ended'
    | 'mobile_settings_opened'
    | 'mobile_default_page_changed'
    | 'mobile_default_page_defaulted'
    | 'mobile_appearance_changed'
    | 'mobile_push_enable_pressed'
    | 'mobile_push_permission_resolved'
    | 'mobile_push_registration_finished'
    | 'mobile_push_received'
    | 'mobile_deep_link_opened'
    | 'mobile_screen_error_shown'
    | 'mobile_screen_error_retried'
    | 'mobile_splash_hidden'
    | 'mobile_create_account_opened'
    | 'mobile_legal_link_opened'
    | 'mobile_inbox_opened'
    | 'mobile_inbox_report_menu_opened'
    | 'mobile_inbox_report_menu_action'
    | 'mobile_inbox_page_requested'
    | 'mobile_inbox_filters_opened'
    | 'mobile_inbox_sort_changed'
    | 'mobile_inbox_created_window_changed'
    | 'mobile_inbox_source_filter_changed'
    | 'mobile_inbox_filters_cleared'
    | 'mobile_inbox_filtered_empty_shown'
    | 'mobile_inbox_report_swiped'
    | 'mobile_report_opened'
    | 'mobile_report_chart_scrubbed'
    | 'mobile_chart_point_selected'
    | 'mobile_chart_tooltip_dismissed'
    | 'mobile_chart_range_compared'
    | 'mobile_chart_legend_toggled'
    | 'mobile_report_insight_opened'
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
    | 'mobile_report_sheet_opened'
    | 'mobile_report_sheet_dismissed'
    | 'mobile_report_action_pressed'
    | 'mobile_report_replay_opened'
    | 'mobile_report_read'
    | 'mobile_report_details_opened'
    | 'mobile_report_details_link_opened'
    | 'mobile_report_details_read'
    | 'mobile_report_load_failed'
    | 'mobile_pull_request_opened'
    | 'mobile_external_handoff_opened'
    | 'mobile_handoff_prompt_copied'
    | 'mobile_handoff_failed'
    | 'mobile_decision_undone'
    | 'mobile_inbox_refreshed'
    | 'mobile_inbox_empty_shown'
    | 'mobile_inbox_error_shown'
    | 'mobile_chat_option_changed'
    | 'mobile_ai_consent_shown'
    | 'mobile_ai_consent_accepted'
    | 'mobile_ai_consent_declined'
    | 'mobile_ai_org_notice_shown'
    | 'mobile_ai_org_settings_opened'
    | 'mobile_session_resumed'
    | 'mobile_session_sent'
    | 'mobile_session_queued'
    | 'mobile_session_queue_removed'
    | 'mobile_session_queue_sent_now'
    | 'mobile_session_stopped'
    | 'mobile_chats_opened'
    | 'mobile_chats_searched'
    | 'mobile_chats_refreshed'
    | 'mobile_chats_load_failed'
    | 'mobile_chat_row_menu_opened'
    | 'mobile_chat_archived'
    | 'mobile_chat_archive_undone'
    | 'mobile_chat_archive_failed'
    | 'mobile_chat_sheet_opened'
    | 'mobile_chat_sheet_closed'
    | 'mobile_chat_mention_opened'
    | 'mobile_chat_report_attached'
    | 'mobile_chat_report_removed'
    | 'mobile_chat_attach_menu_opened'
    | 'mobile_chat_file_attached'
    | 'mobile_chat_file_rejected'
    | 'mobile_chat_file_removed'
    | 'mobile_chat_file_upload_failed'
    | 'mobile_chat_options_opened'
    | 'mobile_chat_draft_restored'
    | 'mobile_chat_suggestion_picked'
    | 'mobile_chat_link_opened'
    | 'mobile_chat_activity_expanded'
    | 'mobile_chat_diagram_failed'
    | 'mobile_session_send_failed'
    | 'mobile_session_finished'
    | 'mobile_session_load_failed'
    | 'mobile_session_load_retried'
    | 'mobile_decision_shown'
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
    | 'mobile_pin_hint_shown'
    | 'mobile_pin_hint_dismissed'
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
    | 'mobile_browse_list_opened'
    | 'mobile_browse_list_paged'
    | 'mobile_nav_pin_changed'
    | 'mobile_nav_tab_web_opened'
    | 'mobile_edit_pins_opened'
    | 'mobile_edit_pins_closed'
    | 'mobile_pin_tile_sheet_opened'
    | 'mobile_pin_tile_sheet_closed'
    | 'mobile_views_error_shown'
    | 'mobile_date_range_sheet_opened'
    | 'mobile_view_more_opened'
    | 'mobile_dashboard_tiles_shown'
    | 'mobile_errors_opened'
    | 'mobile_errors_refreshed'
    | 'mobile_errors_window_changed'
    | 'mobile_errors_filter_changed'
    | 'mobile_errors_opened_in_web'
    | 'mobile_errors_error_shown'
    | 'mobile_issue_opened'
    | 'mobile_issue_status_changed'
    | 'mobile_issue_assigned'
    | 'mobile_issue_chat_opened'
    | 'mobile_issue_frames_expanded'
    | 'mobile_issue_session_opened'
    | 'mobile_issue_link_copied'
    | 'mobile_replay_opened'
    | 'mobile_replay_refreshed'
    | 'mobile_replay_opened_in_web'
    | 'mobile_replay_error_shown'
    | 'mobile_replay_session_opened'
    | 'mobile_replay_full_replay_opened'
    | 'mobile_replay_session_shared'
    | 'mobile_replay_session_id_copied'
    | 'mobile_replay_chapter_opened'
    | 'mobile_replay_summarize_requested'
    | 'mobile_replay_summary_ready'
    | 'mobile_replay_chat_opened'
    | 'mobile_replay_issue_opened'

export type AnalyticsProperties = Record<string, string | number | boolean | null | undefined>

export interface AnalyticsClient {
    capture: (event: AnalyticsEvent, properties?: AnalyticsProperties) => void
    /** Sends a `$screen` event. Optional, so a test double needs only `capture`. */
    screen?: (name: string, properties?: AnalyticsProperties) => void
    captureError?: (error: Error) => void
    identify: (distinctId: string) => void
    /** Starts a new anonymous identity, so the next user on this device is not merged with the last. */
    reset: () => void
}

let client: AnalyticsClient | null = null

// Bounded, because a build without a project key never installs a client to drain it.
const MAX_PENDING = 5
let pending: { event: AnalyticsEvent; properties?: AnalyticsProperties }[] = []

/** `src/lib/posthogClient.ts` installs the client at boot when a project key is set. Until then every call is a no-op. */
export function setAnalyticsClient(next: AnalyticsClient | null): void {
    client = next
    const queued = pending
    pending = []
    if (next) {
        for (const { event, properties } of queued) {
            next.capture(event, properties)
        }
    }
}

export function track(event: AnalyticsEvent, properties?: AnalyticsProperties): void {
    client?.capture(event, properties)
}

/**
 * For code that can run before `initAnalytics()`, such as `app/+native-intent.tsx` on a cold start. The event waits
 * until a client is installed, and is dropped if none ever is.
 */
export function trackWhenReady(event: AnalyticsEvent, properties?: AnalyticsProperties): void {
    if (client) {
        client.capture(event, properties)
    } else if (pending.length < MAX_PENDING) {
        pending.push({ event, properties })
    }
}

export function trackScreen(name: string, properties?: AnalyticsProperties): void {
    client?.screen?.(name, properties)
}

export function captureError(error: Error): void {
    client?.captureError?.(error)
}

export function identify(distinctId: string): void {
    client?.identify(distinctId)
}

export function resetAnalytics(): void {
    client?.reset()
}
