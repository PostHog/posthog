import { track } from '@/lib/analytics'

import type { ReplayVideoErrorKind } from '../video/useReplayVideo'
import type { RenderSpec } from './feedAdapters'
import type { FeedSource, FeedUnit } from './feedModel'

export function trackFeedOpened(props: { source: FeedSource; unit: FeedUnit }): void {
    track('mobile_replay_feed_opened', props)
}

export function trackFeedItemShown(props: {
    sessionId: string
    position: number
    ready: boolean
    unit: FeedUnit
    source: FeedSource
    moments: number
}): void {
    track('mobile_replay_feed_item_shown', {
        session_id: props.sessionId,
        position: props.position,
        ready: props.ready,
        unit: props.unit,
        source: props.source,
        moment_count: props.moments,
    })
}

export function trackFeedRenderRequested(spec: RenderSpec, trigger: 'reuse' | 'dwell' | 'tap'): void {
    track('mobile_replay_feed_render_requested', {
        session_id: spec.sessionId,
        kind: spec.kind,
        trigger,
        seconds: Math.round(spec.kind === 'clip' ? spec.endSeconds - spec.startSeconds : spec.durationSeconds),
    })
}

export function trackFeedRenderReady(spec: RenderSpec, props: { waitedMs: number; reused: boolean }): void {
    track('mobile_replay_feed_render_ready', {
        session_id: spec.sessionId,
        kind: spec.kind,
        waited_ms: props.waitedMs,
        reused: props.reused,
    })
}

export function trackFeedRenderFailed(spec: RenderSpec, kind: ReplayVideoErrorKind | 'playback'): void {
    track('mobile_replay_feed_render_failed', { session_id: spec.sessionId, kind: spec.kind, error: kind })
}

export function trackFeedAutoAdvanced(props: { sessionId: string; to: 'moment' | 'session'; skipped: number }): void {
    track('mobile_replay_feed_auto_advanced', { session_id: props.sessionId, to: props.to, skipped: props.skipped })
}

export function trackFeedEventJump(props: {
    sessionId: string
    direction: 'next' | 'previous'
    kind: string
    via: 'double_tap' | 'info' | 'scrubber'
}): void {
    track('mobile_replay_feed_event_jump', {
        session_id: props.sessionId,
        direction: props.direction,
        kind: props.kind,
        via: props.via,
    })
}

export function trackFeedUnitChanged(props: { unit: FeedUnit; via: 'tab' | 'swipe' | 'info' }): void {
    track('mobile_replay_feed_unit_changed', { unit: props.unit, via: props.via })
}

export function trackFeedSourceChanged(source: FeedSource): void {
    track('mobile_replay_feed_source_changed', { source })
}

export function trackFeedInfoOpened(sessionId: string): void {
    track('mobile_replay_feed_info_opened', { session_id: sessionId })
}

export function trackFeedHoldStarted(props: { sessionId: string; rate: number; locked: boolean }): void {
    track('mobile_replay_feed_hold_started', { session_id: props.sessionId, rate: props.rate, locked: props.locked })
}

export function trackFeedSpeedLocked(rate: number): void {
    track('mobile_replay_feed_speed_locked', { rate, via: 'pull' })
}

export function trackFeedSpeedUnlocked(via: 'pull' | 'settings'): void {
    track('mobile_replay_feed_speed_unlocked', { via })
}

export function trackFeedShared(props: { sessionId: string; action: 'copy_link' | 'open_web' }): void {
    track('mobile_replay_feed_shared', { session_id: props.sessionId, action: props.action })
}

export function trackFeedLoadFailed(props: { sessionId: string; message: string }): void {
    track('mobile_replay_feed_load_failed', { session_id: props.sessionId, message: props.message.slice(0, 120) })
}

export function trackFeedNotInterested(sessionId: string): void {
    track('mobile_replay_feed_not_interested', { session_id: sessionId })
}

export function trackFeedSourcesOpened(props: { source: FeedSource; via: 'swipe' | 'button' }): void {
    track('mobile_replay_feed_sources_opened', { source: props.source, via: props.via })
}

export function trackFeedSessionsChip(source: FeedSource): void {
    track('mobile_replay_feed_sessions_chip_changed', { source })
}

export function trackFeedPlayAll(source: FeedSource): void {
    track('mobile_replay_feed_play_all', { source })
}

export function trackFeedRowPlayed(props: { source: FeedSource; sessionId: string; position: number }): void {
    track('mobile_replay_feed_row_played', {
        source: props.source,
        session_id: props.sessionId,
        position: props.position,
    })
}
