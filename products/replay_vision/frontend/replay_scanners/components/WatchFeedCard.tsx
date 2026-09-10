import { IconPlay } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { ObservationResultSummary, readResult } from '../../components/ObservationCard'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import type { ReplayObservationApi, WatchFeedItemApi, WatchFeedReasonApi } from '../../generated/api.schemas'
import { citedTimestampRange } from '../../utils/citations'
import { ScannerType } from '../types'

export function watchReasonCopy(reason: WatchFeedReasonApi): string {
    switch (reason.kind) {
        case 'signal_emitted':
            return (reason.signals_count ?? 0) > 1
                ? `The scanner raised ${reason.signals_count} signals from this session.`
                : 'The scanner raised a signal from this session.'
        case 'verdict_yes':
            return 'The scanner answered yes for this session.'
        case 'outlier_score':
            return `Scored ${reason.score}, far from this scanner's recent average of ${reason.window_mean}.`
        case 'rare_tag':
            return `Tagged "${reason.tag}", which is uncommon for this scanner lately.`
        case 'unviewed_recent':
            return 'New since you last looked.'
        case 'recent':
            return 'The newest from this scanner.'
    }
}

/** The moment span the observation cites, read from the type's cited field. */
export function observationClipRange(observation: ReplayObservationApi): { startMs: number; endMs: number } | null {
    const result = readResult(observation)
    if (!result) {
        return null
    }
    const scannerType = result.scanner_type as ScannerType | undefined
    const [text, segments] =
        scannerType === 'summarizer'
            ? [result.summary, result.summary_segments]
            : [result.reasoning, result.reasoning_segments]
    return typeof text === 'string' ? citedTimestampRange(text, segments) : null
}

interface WatchFeedCardProps {
    item: WatchFeedItemApi
    /** Zero-based place in the feed, captured so we can see how deep people read. */
    position: number
}

export function WatchFeedCard({ item, position }: WatchFeedCardProps): JSX.Element {
    const { observation, reason } = item
    const clip = observationClipRange(observation)
    const scannerType = observation.scanner_snapshot?.scanner_type as ScannerType | undefined
    const scannerName = (observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)'
    const person = observation.recording_subject_email || observation.distinct_id
    const watchUrl = `${urls.replayVisionObservation(observation.id)}${
        clip ? `?t=${Math.floor(clip.startMs / 1000)}` : ''
    }`
    const captureClick = (): void => {
        posthog.capture('replay_vision_watch_clip_clicked', {
            scanner_id: observation.scanner_id,
            scanner_type: scannerType,
            observation_id: observation.id,
            position,
            reason_kind: reason.kind,
        })
    }

    return (
        <div className="@container border rounded bg-bg-light p-4 flex gap-4" data-attr="vision-watch-feed-card">
            <div className="hidden @xl:flex w-48 shrink-0 flex-col gap-1">
                <div className="h-24 rounded bg-surface-secondary border flex items-center justify-center relative">
                    <IconPlay className="text-2xl text-muted" />
                    {clip && (
                        <span className="absolute bottom-1 right-1 text-xs tabular-nums bg-bg-light border rounded px-1">
                            {colonDelimitedDuration(Math.floor(clip.startMs / 1000), null)} to{' '}
                            {colonDelimitedDuration(Math.floor(clip.endMs / 1000), null)}
                        </span>
                    )}
                </div>
                {clip && clip.endMs > clip.startMs && (
                    <span className="text-xs text-muted">
                        {colonDelimitedDuration(Math.ceil((clip.endMs - clip.startMs) / 1000), null)} of the session
                        cited
                    </span>
                )}
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    {!observation.viewed && (
                        <Tooltip title="You haven't opened this observation yet">
                            <span className="w-2 h-2 rounded-full bg-accent shrink-0" aria-label="Unviewed" />
                        </Tooltip>
                    )}
                    {scannerType && <ScannerTypeBadge scannerType={scannerType} />}
                    <span className="text-muted text-sm truncate">{scannerName}</span>
                </div>
                <div className="text-sm">
                    <ObservationResultSummary observation={observation} />
                </div>
                <div className="text-xs text-secondary">
                    <span className="font-semibold uppercase">Why this clip</span> {watchReasonCopy(reason)}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted mt-auto">
                    <span className="truncate">{person}</span>
                    <TZLabel time={observation.created_at} className="shrink-0" />
                </div>
            </div>
            <div className="shrink-0 flex flex-col items-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlay />}
                    to={watchUrl}
                    onClick={captureClick}
                    data-attr="vision-watch-clip"
                >
                    Watch clip
                </LemonButton>
            </div>
        </div>
    )
}
