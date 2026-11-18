import type { ReplayVideoExport } from '@/api/replayVideo'
import type { RecordingView, SessionSummary } from '../replayModel'

export type FeedSource = 'highlights' | 'rage' | 'errors' | 'newest'

export const FEED_SOURCES: readonly FeedSource[] = ['highlights', 'rage', 'errors', 'newest']

export type FeedUnit = 'moment' | 'session'

export type FeedEventKind = 'pageview' | 'click' | 'rageclick' | 'deadclick' | 'exception' | 'custom'

export interface FeedEvent {
    key: string
    kind: FeedEventKind
    /** Seconds from the recording start, on the session clock. */
    seconds: number
    label: string
    target: string | null
}

export interface FeedTimeline {
    events: FeedEvent[]
    browser: string | null
    os: string | null
    viewport: { width: number; height: number } | null
}

export type MomentKind = 'rageclick' | 'exception' | 'key' | 'custom' | 'start'

export interface Moment {
    key: string
    kind: MomentKind
    anchorSeconds: number
    startSeconds: number
    endSeconds: number
    label: string
}

export interface FeedItem {
    recording: RecordingView
    summary: SessionSummary | null
    /** The current user's newest whole-recording or clip exports of this session, newest first. */
    exports: ReplayVideoExport[]
    readyAtLoad: boolean
}

export interface FeedSettings {
    speed: number
    autoplayNext: boolean
    startAt: 'key' | 'beginning'
    leadInSeconds: number
    momentSeconds: number
    phoneFit: 'fill' | 'whole'
    skipInactivity: boolean
}

export const SPEED_PRESETS: readonly number[] = [0.5, 1, 1.5, 2, 3, 4, 8, 16]
export const LEAD_IN_PRESETS: readonly number[] = [3, 5, 10]
export const MOMENT_LENGTH_PRESETS: readonly number[] = [15, 20, 30, 45]
