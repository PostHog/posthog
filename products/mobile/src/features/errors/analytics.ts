import type { ErrorsWindow, IssueStatusApi } from '@/api/errorTracking'
import { track } from '@/lib/analytics'

import type { IssueFilter } from './issueModel'

// Typed wrappers for the error tracking events, so every screen sends the same property names and values.

export type ErrorsChrome = 'tab' | 'stack'
export type IssueOpenSource = 'list' | 'link' | 'replay' | 'other'
export type ErrorsErrorKind = 'list_failed' | 'issue_failed' | 'issue_not_found' | 'status_failed' | 'assign_failed'

const OPEN_SOURCES: readonly IssueOpenSource[] = ['list', 'link', 'replay', 'other']

/** The `from` route param. A link from outside the app arrives without one. */
export function issueOpenSourceParam(value: string | string[] | undefined): IssueOpenSource {
    const first = Array.isArray(value) ? value[0] : value
    return OPEN_SOURCES.find((source) => source === first) ?? 'other'
}

export function trackErrorsOpened(props: { chrome: ErrorsChrome; window: ErrorsWindow }): void {
    track('mobile_errors_opened', { chrome: props.chrome, window: props.window })
}

export function trackErrorsRefreshed(props: { window: ErrorsWindow }): void {
    track('mobile_errors_refreshed', { window: props.window })
}

export function trackErrorsWindowChanged(props: { window: ErrorsWindow }): void {
    track('mobile_errors_window_changed', { window: props.window })
}

export function trackErrorsFilterChanged(props: { filter: IssueFilter }): void {
    track('mobile_errors_filter_changed', { filter: props.filter })
}

export function trackErrorsOpenedInWeb(props: { screen: 'list' | 'issue' }): void {
    track('mobile_errors_opened_in_web', { screen: props.screen })
}

export function trackErrorsErrorShown(props: { kind: ErrorsErrorKind }): void {
    track('mobile_errors_error_shown', { kind: props.kind })
}

export function trackIssueOpened(props: { source: IssueOpenSource; status: IssueStatusApi }): void {
    track('mobile_issue_opened', { source: props.source, status: props.status })
}

export function trackIssueStatusChanged(props: { from: IssueStatusApi; to: IssueStatusApi; undo: boolean }): void {
    track('mobile_issue_status_changed', { from: props.from, to: props.to, undo: props.undo })
}

export function trackIssueAssigned(props: { self: boolean; assigned: boolean }): void {
    track('mobile_issue_assigned', { self: props.self, assigned: props.assigned })
}

export function trackIssueChatOpened(): void {
    track('mobile_issue_chat_opened')
}

export function trackIssueFramesExpanded(props: { frames: number }): void {
    track('mobile_issue_frames_expanded', { frames: props.frames })
}

export function trackIssueSessionOpened(props: { position: number }): void {
    track('mobile_issue_session_opened', { position: props.position })
}

export function trackIssueLinkCopied(): void {
    track('mobile_issue_link_copied')
}
