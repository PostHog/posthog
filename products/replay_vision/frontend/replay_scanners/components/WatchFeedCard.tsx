import { useActions } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconFlag, IconPlay, IconPlayFilled } from '@posthog/icons'
import { LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { CitedText, ObservationResultSummary, readResult } from '../../components/ObservationCard'
import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import type { ReplayObservationApi, WatchFeedItemApi, WatchFeedReasonApi } from '../../generated/api.schemas'
import { OBSERVATION_ORIGIN_PARAM, WATCH_FEED_ORIGIN } from '../../utils/breadcrumbs'
import { citedTextToPlainText, citedTimestampRange } from '../../utils/citations'
import { ScannerType } from '../types'

const roundScore = (value: number): number => Math.round(value * 100) / 100

const PROBLEM_TYPE_LABELS: Record<string, string> = {
    bug: 'bug',
    crash: 'crash',
    design_flaw: 'design flaw',
    ux_friction: 'UX friction',
}

const problemTypeLabel = (problemType: string): string =>
    PROBLEM_TYPE_LABELS[problemType] ?? problemType.replace(/_/g, ' ')

// A card lists the findings on one line, so it names the first few and counts the rest.
const MAX_SHOWN_HEADLINES = 3

const joinWithAnd = (parts: string[]): string =>
    parts.length > 1 ? `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}` : parts[0]

/** Reason kinds that say nothing about the session. The backend returns these only to pad a near-empty
 * feed, so a feed made up entirely of them means the window turned up no findings at all. */
export const FILLER_REASON_KINDS = new Set(['unviewed_recent', 'recent'])

export function watchReasonCopy(reason: WatchFeedReasonApi): string {
    // The scan wrote this sentence while watching the session, so it beats anything derived from the
    // reason kind. Absent on observations scanned before notability shipped, which fall through below.
    if (reason.notability_reason) {
        return reason.notability_reason
    }
    switch (reason.kind) {
        case 'signal_emitted': {
            const total = reason.signals_count ?? 0
            const signals = reason.signals ?? []
            const problemTypes =
                signals.length > 0 ? signals.map((signal) => signal.problem_type) : (reason.problem_types ?? [])
            if (problemTypes.length === 0) {
                return total > 1
                    ? `The scanner raised ${total} signals from this session.`
                    : 'The scanner raised a signal from this session.'
            }
            // Count each problem type, keeping the order the scan first raised them.
            const order: string[] = []
            const countByType = new Map<string, number>()
            for (const problemType of problemTypes) {
                if (!countByType.has(problemType)) {
                    order.push(problemType)
                }
                countByType.set(problemType, (countByType.get(problemType) ?? 0) + 1)
            }
            // Sessions scanned before headlines shipped carry the types alone, so those cards still count.
            if (signals.length === 0) {
                if (order.length === 1) {
                    const label = problemTypeLabel(order[0])
                    return total > 1
                        ? `The scanner raised ${total} ${label} signals from this session.`
                        : `The scanner raised a ${label} signal from this session.`
                }
                const breakdown = order
                    .map((problemType) => {
                        const n = countByType.get(problemType) ?? 0
                        return `${n} ${problemTypeLabel(problemType)} signal${n === 1 ? '' : 's'}`
                    })
                    .join(', ')
                return `The scanner raised ${total} signals from this session: ${breakdown}.`
            }
            const shown = signals.slice(0, MAX_SHOWN_HEADLINES)
            // Against the count, not the named list: the backend drops a finding whose headline came back
            // blank, so the card can hold fewer names than the session raised signals.
            const hidden = Math.max(total, signals.length) - shown.length
            if (order.length === 1) {
                const label = problemTypeLabel(order[0])
                const named = shown.map((signal) => signal.headline)
                const listed = joinWithAnd(hidden > 0 ? [...named, `${hidden} more`] : named)
                return total > 1
                    ? `The scanner raised ${total} ${label} signals from this session: ${listed}.`
                    : `The scanner raised a ${label} signal from this session: ${listed}.`
            }
            const groups = order.map((problemType) => {
                const n = countByType.get(problemType) ?? 0
                const named = shown
                    .filter((signal) => signal.problem_type === problemType)
                    .map((signal) => signal.headline)
                const label = `${n} ${problemTypeLabel(problemType)}`
                return named.length > 0 ? `${label} (${named.join(', ')})` : label
            })
            const listed = joinWithAnd(hidden > 0 ? [...groups, `${hidden} more`] : groups)
            return `The scanner raised ${total} signals from this session: ${listed}.`
        }
        case 'unusual_verdict':
            return reason.verdict
                ? `The scanner answered ${reason.verdict}, which is rare for it in this window.`
                : 'The scanner gave a rare answer for this window.'
        case 'verdict_yes':
            return 'The scanner answered yes for this session.'
        case 'outlier_score':
            return reason.score != null && reason.window_mean != null
                ? `Scored ${roundScore(reason.score)}, far from this scanner's recent average of ${roundScore(reason.window_mean)}.`
                : "Scored far from this scanner's recent average."
        case 'rare_tag':
            return reason.tag
                ? `Tagged "${reason.tag}", which is uncommon for this scanner lately.`
                : 'Tagged something uncommon for this scanner lately.'
        case 'novel_summary':
            return "Reads unlike this scanner's other sessions in this window."
        case 'notable':
            return 'The scanner judged this session worth watching.'
        case 'friction':
            return 'The session shows signs of friction, like errors, retries, or dead ends.'
        case 'unviewed_recent':
            return 'New since you last looked.'
        case 'recent':
            return 'The newest from this scanner.'
        default:
            // The backend owns this enum, so a kind that ships before this frontend deploys still needs a sentence.
            return 'Worth a look.'
    }
}

/** The moment span the observation cites, read from the type's cited field. */
export function observationClipRange(observation: ReplayObservationApi): { startMs: number; endMs: number } | null {
    const result = readResult(observation)
    if (!result) {
        return null
    }
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result.scanner_type as ScannerType | undefined)
    const [text, segments] =
        scannerType === 'summarizer'
            ? [result.summary, result.summary_segments]
            : [result.reasoning, result.reasoning_segments]
    return typeof text === 'string' ? citedTimestampRange(text, segments) : null
}

/**
 * The card's bold headline, plus the prose that follows it. A summarizer authored a title, so its
 * summary rides along whole (with citation chips). Otherwise the first sentence of the prose the
 * scan wrote (an untitled summarizer's summary, the other types' reasoning) is promoted to the
 * headline, with citation chips rendered as plain timestamps so a mid-sentence citation keeps
 * its place, and the rest becomes the body, already plain.
 */
export function watchCardHeadline(
    observation: ReplayObservationApi
): { title: string; body: { text: string; segments?: unknown } | null } | null {
    const result = readResult(observation)
    if (!result) {
        return null
    }
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result.scanner_type as ScannerType | undefined)
    if (scannerType === 'summarizer' && typeof result.title === 'string' && result.title) {
        const summary = typeof result.summary === 'string' ? result.summary : null
        return {
            title: result.title,
            body: summary ? { text: summary, segments: result.summary_segments } : null,
        }
    }
    // The summarizer's title defaults to "", so an untitled summary still earns a derived headline.
    const [text, segments] =
        scannerType === 'summarizer'
            ? [result.summary, result.summary_segments]
            : [result.reasoning, result.reasoning_segments]
    if (typeof text !== 'string' || !text) {
        return null
    }
    const plain = citedTextToPlainText(text, segments).replace(/\s+/g, ' ').trim()
    if (!plain) {
        return null
    }
    // A sentence ends at ./!/? followed by whitespace and a non-lowercase character, so "9.5",
    // "$0.50", "e.g. this", and "8 vs. 5" never split mid-sentence.
    const match = plain.match(/^[\s\S]*?[.!?](?=\s+(?![a-z])|$)/)
    const title = (match?.[0] ?? plain).trim()
    const rest = plain.slice(match?.[0]?.length ?? plain.length).trim()
    return { title, body: rest ? { text: rest } : null }
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
    const result = readResult(observation)
    // Fall back to the result's own scanner_type when the snapshot is absent, like observationClipRange,
    // so a scan with no snapshot still places its outcome in the right spot.
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    const scannerName = (observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)'
    const person = observation.recording_subject_email || observation.distinct_id
    const headline = watchCardHeadline(observation)
    const clipDuration =
        clip && clip.endMs > clip.startMs
            ? colonDelimitedDuration(Math.ceil((clip.endMs - clip.startMs) / 1000), null)
            : null
    // t=0 when nothing is cited, so the observation page still opens with the player expanded. `from`
    // marks the feed as the origin, so the observation's back button returns here rather than the scanner.
    const observationUrl = combineUrl(urls.replayVisionObservation(observation.id), {
        t: clip ? Math.floor(clip.startMs / 1000) : 0,
        [OBSERVATION_ORIGIN_PARAM]: WATCH_FEED_ORIGIN,
    }).url
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
            {/* The thumbnail is the watch affordance, so the whole poster opens the clip modal.
                The dot and the duration sit outside the poster, which clips its own overflow. */}
            <div className="relative hidden @md:block w-64 shrink-0 self-start">
                <button
                    type="button"
                    onClick={watchClipInModal}
                    className="relative z-10 block w-full cursor-pointer"
                    data-attr="vision-watch-clip"
                    aria-label="Watch clip"
                >
                    <ObservationThumbnail observation={observation}>
                        <span className="flex items-center gap-1.5 rounded-full bg-black/70 px-3 py-1 text-xs font-semibold text-white">
                            <IconPlayFilled aria-hidden />
                            {clipDuration ? `Watch ${clipDuration}` : 'Watch clip'}
                        </span>
                    </ObservationThumbnail>
                    {clip && (
                        <span className="absolute bottom-1 right-1 text-xs tabular-nums bg-bg-light border rounded px-1">
                            {colonDelimitedDuration(Math.floor(clip.startMs / 1000), null)} to{' '}
                            {colonDelimitedDuration(Math.floor(clip.endMs / 1000), null)}
                        </span>
                    )}
                </button>
                {!observation.viewed && (
                    <Tooltip title="You haven't opened this observation yet">
                        <span
                            className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-accent border border-bg-light z-10"
                            aria-label="Unviewed"
                        />
                    </Tooltip>
                )}
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                {/* Stretched to cover the card: clicking anywhere opens the observation with the
                    player expanded at the first cited moment. Inner links and the thumbnail button
                    sit above it via `relative z-10`, so the anchors never nest. */}
                <Link
                    to={observationUrl}
                    onClick={() => capture('observation')}
                    className="text-default after:absolute after:inset-0 after:content-['']"
                    data-attr="vision-watch-feed-card-body"
                >
                    <h3 className="text-sm font-semibold m-0 line-clamp-2">{headline?.title ?? scannerName}</h3>
                </Link>
                <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                    {person &&
                        (observation.distinct_id ? (
                            <Link
                                to={urls.personByDistinctId(observation.distinct_id)}
                                className="relative z-10 truncate min-w-0 text-muted"
                                data-attr="vision-watch-feed-person"
                            >
                                {person}
                            </Link>
                        ) : (
                            <span className="truncate min-w-0">{person}</span>
                        ))}
                    {person && <span aria-hidden>·</span>}
                    <TZLabel time={observation.created_at} className="shrink-0" />
                </div>
                {/* Above the overlay link so the outcome's hover tooltip stays reachable. The
                    summarizer's outcome is the title + body above, so it adds no chip here. */}
                <div className="relative z-10 flex flex-wrap items-center gap-2 min-w-0">
                    {scannerType && <ScannerTypeBadge scannerType={scannerType} />}
                    <span className="text-muted text-xs truncate">{scannerName}</span>
                    {scannerType !== 'summarizer' && <ObservationResultSummary observation={observation} />}
                </div>
                {headline?.body && (
                    <p className="text-muted text-xs m-0 line-clamp-2">
                        <CitedText text={headline.body.text} segments={headline.body.segments} />
                    </p>
                )}
                <div className="flex items-start gap-1.5 text-xs text-muted">
                    <IconFlag className="mt-0.5 shrink-0 text-accent" aria-hidden />
                    <span>{watchReasonCopy(reason)}</span>
                </div>
                {/* Narrow containers hide the thumbnail, so they keep an explicit watch control. */}
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconPlay />}
                    onClick={watchClipInModal}
                    className="@md:hidden self-start relative z-10"
                    data-attr="vision-watch-clip"
                >
                    Watch clip
                </LemonButton>
            </div>
        </div>
    )
}
