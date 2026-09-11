import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonDivider, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { CitedText, ObservationResultSummary, readResult } from '../../components/ObservationCard'
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
        case 'unusual_verdict':
            return `The scanner answered ${reason.verdict}, which is rare for it in this window.`
        case 'verdict_yes':
            return 'The scanner answered yes for this session.'
        case 'outlier_score':
            return `Scored ${reason.score}, far from this scanner's recent average of ${reason.window_mean}.`
        case 'rare_tag':
            return `Tagged "${reason.tag}", which is uncommon for this scanner lately.`
        case 'novel_summary':
            return "Reads unlike this scanner's other sessions in this window."
        case 'friction':
            return 'The session shows signs of friction, like errors, retries, or dead ends.'
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
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const clip = observationClipRange(observation)
    const scannerType = observation.scanner_snapshot?.scanner_type as ScannerType | undefined
    const scannerName = (observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)'
    const person = observation.recording_subject_email || observation.distinct_id
    // Summarizers already tell the story through title + summary; the other types show only an
    // outcome chip, so bring their reasoning along for context, clamped to keep the card scannable.
    const result = readResult(observation)
    const reasoning =
        scannerType !== 'summarizer' && typeof result?.reasoning === 'string'
            ? { text: result.reasoning, segments: result.reasoning_segments }
            : null
    // t=0 when nothing is cited, so the observation page still opens with the player expanded.
    const observationUrl = `${urls.replayVisionObservation(observation.id)}?t=${clip ? Math.floor(clip.startMs / 1000) : 0}`
    const capture = (target: 'clip_modal' | 'observation'): void => {
        posthog.capture('replay_vision_watch_clip_clicked', {
            scanner_id: observation.scanner_id,
            scanner_type: scannerType,
            observation_id: observation.id,
            position,
            reason_kind: reason.kind,
            target,
        })
    }
    const watchClipInModal = (): void => {
        capture('clip_modal')
        // The modal's own `initialTimestamp` is an absolute unix-ms time, but a clip start is an
        // offset into the recording. The player reads `?t=<seconds>` as an offset on first load and
        // the modal preserves existing search params, so set (or clear) `t` before opening.
        const { location, searchParams, hashParams } = router.values
        router.actions.replace(
            location.pathname,
            { ...searchParams, t: clip ? Math.floor(clip.startMs / 1000) : undefined },
            hashParams
        )
        openSessionPlayer({ id: observation.session_id })
    }

    return (
        <div
            className="@container relative border rounded bg-bg-light p-4 flex gap-4 hover:border-accent"
            data-attr="vision-watch-feed-card"
        >
            {/* The thumbnail column spans the card's full height; everything else stacks beside it. */}
            <div className="hidden @md:flex w-48 shrink-0 flex-col gap-1">
                <div className="h-24 rounded bg-surface-secondary border flex items-center justify-center relative">
                    <IconPlay className="text-2xl text-muted" />
                    {!observation.viewed && (
                        <Tooltip title="You haven't opened this observation yet">
                            <span
                                className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-accent border border-bg-light z-10"
                                aria-label="Unviewed"
                            />
                        </Tooltip>
                    )}
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
                <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                        {scannerType && <ScannerTypeBadge scannerType={scannerType} />}
                        <span className="text-muted text-sm truncate">{scannerName}</span>
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlay />}
                        onClick={watchClipInModal}
                        className="relative z-10 shrink-0"
                        data-attr="vision-watch-clip"
                    >
                        Watch clip
                    </LemonButton>
                </div>
                {/* Stretched to cover the card: clicking anywhere opens the observation with the
                    player expanded at the first cited moment. Inner links and the button sit
                    above it via `relative z-10`, so the anchors never nest. */}
                <Link
                    to={observationUrl}
                    onClick={() => capture('observation')}
                    className="text-sm text-default after:absolute after:inset-0 after:content-['']"
                    data-attr="vision-watch-feed-card-body"
                >
                    <div className="flex flex-col gap-1">
                        <ObservationResultSummary observation={observation} />
                        {reasoning && (
                            <p className="text-muted m-0 line-clamp-2">
                                <CitedText text={reasoning.text} segments={reasoning.segments} />
                            </p>
                        )}
                    </div>
                </Link>
                <LemonDivider className="my-0" />
                <div className="text-xs text-secondary">
                    <span className="font-semibold uppercase">Why this clip</span> {watchReasonCopy(reason)}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                    {person ? (
                        observation.distinct_id ? (
                            <Link
                                to={urls.personByDistinctId(observation.distinct_id)}
                                className="relative z-10 flex items-center gap-1.5 min-w-0"
                                data-attr="vision-watch-feed-person"
                            >
                                <ProfilePicture
                                    user={{ email: observation.recording_subject_email ?? undefined }}
                                    name={person}
                                    size="sm"
                                />
                                <span className="truncate">{person}</span>
                            </Link>
                        ) : (
                            <span className="flex items-center gap-1.5 min-w-0">
                                <ProfilePicture
                                    user={{ email: observation.recording_subject_email ?? undefined }}
                                    name={person}
                                    size="sm"
                                />
                                <span className="truncate">{person}</span>
                            </span>
                        )
                    ) : (
                        <span />
                    )}
                    <TZLabel time={observation.created_at} className="shrink-0" />
                </div>
            </div>
        </div>
    )
}
