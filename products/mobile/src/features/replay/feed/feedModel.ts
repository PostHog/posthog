import type { ReplayVideoExport } from '@/api/replayVideo'
import type { RecordingView, SessionSummary } from '../replayModel'

export type FeedSource = 'highlights' | 'rage' | 'errors' | 'newest'

export const FEED_SOURCES: readonly FeedSource[] = ['highlights', 'rage', 'errors', 'newest']

export type FeedUnit = 'moment' | 'session'

/** The two tabs at the top of the feed, in order. "Highlights" names a source, so the first tab is not called that. */
export const FEED_TAB_LABELS: Record<FeedUnit, string> = { moment: 'Moment', session: 'Full recording' }

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
    skipInactivity: boolean
}

export const SPEED_PRESETS: readonly number[] = [0.5, 1, 1.5, 2, 4]

/** A stored speed from before the shorter list maps to the nearest one that is still offered. */
export function normalizeSpeed(speed: unknown): number {
    if (typeof speed !== 'number' || !Number.isFinite(speed)) {
        return 1
    }
    if (SPEED_PRESETS.includes(speed)) {
        return speed
    }
    return speed >= 4 ? 4 : speed >= 2 ? 2 : 1
}

/** How a moment is cut around its anchor: the lead-in plays first, and the moment lasts this long. */
export interface MomentWindow {
    leadInSeconds: number
    momentSeconds: number
}

export const MOMENT_WINDOW: MomentWindow = { leadInSeconds: 5, momentSeconds: 20 }
