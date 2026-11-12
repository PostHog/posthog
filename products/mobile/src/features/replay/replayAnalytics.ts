import type { ScanOutcomeApi } from '@/api/replayVision'
import { track } from '@/lib/analytics'
import type { SessionOpenSource } from './replayLinks'
import type { ReplayVideoErrorKind, ReplayVideoState } from './video/useReplayVideo'

// Properties are enums, ids and counts only. Session ids are product ids, the same as report ids in other events.

export function trackReplayListOpened(chrome: 'tab' | 'stack'): void {
    track('mobile_replay_opened', { chrome })
}

export function trackReplayRefreshed(rowCount: number): void {
    track('mobile_replay_refreshed', { row_count: rowCount })
}

export function trackReplayOpenedInWeb(from: 'list' | 'session'): void {
    track('mobile_replay_opened_in_web', { from })
}

export type ReplayErrorKind = 'list' | 'recording' | 'not_found' | 'timeline' | 'summary' | 'summarize' | 'frame'

export function trackReplayErrorShown(kind: ReplayErrorKind): void {
    track('mobile_replay_error_shown', { kind })
}

export function trackSessionOpened(props: { sessionId: string; source: SessionOpenSource; hasSummary: boolean }): void {
    track('mobile_replay_session_opened', {
        session_id: props.sessionId,
        source: props.source,
        has_summary: props.hasSummary,
    })
}

export function trackFullReplayOpened(sessionId: string): void {
    track('mobile_replay_full_replay_opened', { session_id: sessionId })
}

export function trackSessionShared(sessionId: string, seconds: number): void {
    track('mobile_replay_session_shared', { session_id: sessionId, seconds })
}

export function trackSessionIdCopied(sessionId: string): void {
    track('mobile_replay_session_id_copied', { session_id: sessionId })
}

export function trackChapterOpened(props: { sessionId: string; index: number; isKeyMoment: boolean }): void {
    track('mobile_replay_chapter_opened', {
        session_id: props.sessionId,
        chapter_index: props.index,
        is_key_moment: props.isKeyMoment,
    })
}

export function trackSummarizeRequested(sessionId: string, outcome: ScanOutcomeApi | 'error' | null): void {
    track('mobile_replay_summarize_requested', { session_id: sessionId, outcome })
}

export function trackSummaryReady(sessionId: string, seconds: number): void {
    track('mobile_replay_summary_ready', { session_id: sessionId, seconds })
}

export function trackSessionChatOpened(sessionId: string): void {
    track('mobile_replay_chat_opened', { session_id: sessionId })
}

export function trackSessionIssueOpened(sessionId: string): void {
    track('mobile_replay_issue_opened', { session_id: sessionId })
}

export function trackReplayVideoRequested(sessionId: string): void {
    track('mobile_replay_video_requested', { session_id: sessionId })
}

export function trackReplayVideoReady(sessionId: string, props: { waitedMs: number; reused: boolean }): void {
    track('mobile_replay_video_ready', { session_id: sessionId, waited_ms: props.waitedMs, reused: props.reused })
}

/** `playback` is the native player failing on a video the server says is ready. */
export type ReplayVideoFailureKind = ReplayVideoErrorKind | 'playback'

export function trackReplayVideoFailed(sessionId: string, kind: ReplayVideoFailureKind): void {
    track('mobile_replay_video_failed', { session_id: sessionId, kind })
}

export function trackReplayVideoClosed(sessionId: string, props: { status: ReplayVideoState['status'] }): void {
    track('mobile_replay_video_closed', { session_id: sessionId, status: props.status })
}
