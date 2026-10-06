import { useActions } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconFlag, IconPlay, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { CitedText, ObservationResultSummary, readResult } from '../../components/ObservationCard'
import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { UnviewedObservationTag } from '../../components/UnviewedObservationTag'
import type { ReplayObservationApi, WatchFeedItemApi, WatchFeedReasonApi } from '../../generated/api.schemas'
import { OBSERVATION_ORIGIN_PARAM, WATCH_FEED_ORIGIN } from '../../utils/breadcrumbs'
import { citedTextToPlainText } from '../../utils/citations'
import { ScannerType } from '../types'
import { type WatchFeedView, watchFeedLogic } from '../watchFeedLogic'

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
        case 'jev_watchable':
            return 'The decision model judged this session worth watching.'
        case 'unviewed_recent':
            return 'New since you last looked.'
        case 'recent':
            return 'The newest from this scanner.'
        default:
            // The backend owns this enum, so a kind that ships before this frontend deploys still needs a sentence.
            return 'Worth a look.'
    }
}

/** Seconds of lead-in before the key moment, so the viewer sees what led up to it. */
const KEY_MOMENT_LEAD_IN_S = 3

/** The session offset of the moment the scan's answer rests on most, or null on scans that did not pick one. */
export function observationKeyMomentMs(observation: ReplayObservationApi): number | null {
    const keyMomentMs = readResult(observation)?.key_moment_ms
    return typeof keyMomentMs === 'number' && Number.isFinite(keyMomentMs) && keyMomentMs >= 0 ? keyMomentMs : null
}

/** Where the player starts: a short lead-in before the key moment, or the recording's start without one. */
export function watchStartSeconds(keyMomentMs: number | null): number {
    return keyMomentMs === null ? 0 : Math.max(0, Math.floor(keyMomentMs / 1000) - KEY_MOMENT_LEAD_IN_S)
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

interface WatchFeedCardData {
    keyMomentMs: number | null
    scannerType: ScannerType | undefined
    scannerName: string
    person: string | null | undefined
    headline: ReturnType<typeof watchCardHeadline>
    observationUrl: string
    captureObservationOpened: () => void
    watchClipInModal: () => void
}

/** What both card layouts show and do, so the grid and the list open and report clips the same way. */
function useWatchFeedCardData(
    { observation, reason }: WatchFeedItemApi,
    position: number,
    view: WatchFeedView
): WatchFeedCardData {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const result = readResult(observation)
    // Fall back to the result's own scanner_type when the snapshot is absent, like watchCardHeadline,
    // so a scan with no snapshot still places its outcome in the right spot.
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    const scannerName = (observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)'
    const person = observation.recording_subject_email || observation.distinct_id
    const headline = watchCardHeadline(observation)
    const keyMomentMs = observationKeyMomentMs(observation)
    const startSeconds = watchStartSeconds(keyMomentMs)
    // t is always set, so the observation page opens with the player expanded. `from` marks the feed as the
    // origin, so the observation's back button returns here rather than the scanner.
    const observationUrl = combineUrl(urls.replayVisionObservation(observation.id), {
        t: startSeconds,
        [OBSERVATION_ORIGIN_PARAM]: WATCH_FEED_ORIGIN,
    }).url
    const capture = (target: 'clip_modal' | 'observation'): void => {
        posthog.capture('replay_vision_watch_clip_clicked', {
            scanner_id: observation.scanner_id,
            scanner_type: scannerType,
            observation_id: observation.id,
            position,
            reason_kind: reason.kind,
            has_key_moment: keyMomentMs !== null,
            target,
            view,
        })
    }
    const watchClipInModal = (): void => {
        capture('clip_modal')
        // The modal's own `initialTimestamp` is an absolute unix-ms time, but the key moment is an offset
        // into the recording. The player reads `?t=<seconds>` as an offset on first load and the modal
        // preserves existing search params, so set `t` before opening. Without a key moment, clear any stale
        // `t` so the clip starts from the beginning.
        const { location, searchParams, hashParams } = router.values
        router.actions.replace(
            location.pathname,
            { ...searchParams, t: keyMomentMs === null ? undefined : startSeconds },
            hashParams
        )
        openSessionPlayer({ id: observation.session_id })
    }
    return {
        keyMomentMs,
        scannerType,
        scannerName,
        person,
        headline,
        observationUrl,
        captureObservationOpened: () => capture('observation'),
        watchClipInModal,
    }
}

function WatchClipPoster({
    observation,
    keyMomentMs,
    onWatch,
    className,
}: {
    observation: ReplayObservationApi
    keyMomentMs: number | null
    onWatch: () => void
    className?: string
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onWatch}
            className="relative z-10 block w-full cursor-pointer"
            data-attr="vision-watch-clip"
            aria-label="Watch clip"
        >
            <ObservationThumbnail observation={observation} className={className}>
                <span className="flex items-center gap-1.5 rounded-full bg-black/70 px-3 py-1 text-xs font-semibold text-white">
                    <IconPlayFilled aria-hidden />
                    Watch clip
                </span>
            </ObservationThumbnail>
            {keyMomentMs !== null && (
                <Tooltip title="Key moment: where the scan's answer rests most. The clip starts just before it.">
                    <span className="absolute bottom-1 right-1 text-xs tabular-nums bg-bg-light border rounded px-1">
                        {colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null)}
                    </span>
                </Tooltip>
            )}
        </button>
    )
}

function WatchCardPerson({
    observation,
    person,
}: {
    observation: ReplayObservationApi
    person: string | null | undefined
}): JSX.Element {
    return (
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
    )
}

function WatchCardScanner({
    observation,
    scannerType,
    scannerName,
}: {
    observation: ReplayObservationApi
    scannerType: ScannerType | undefined
    scannerName: string
}): JSX.Element {
    return (
        // Above the overlay link so the outcome's hover tooltip stays reachable. The summarizer's
        // outcome is the title + body, so it adds no chip here.
        <div className="relative z-10 flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
            {/* One text flow, so on a narrow card the question starts beside the badge and wraps under it
                instead of the whole question dropping to its own line. */}
            <p className="m-0 min-w-0 text-xs leading-5">
                {scannerType && (
                    <span className="inline-flex align-middle mr-1.5">
                        <ScannerTypeBadge scannerType={scannerType} />
                    </span>
                )}
                {/* The question says what the result answers; the scanner's name is a hover away. */}
                {observation.prompt_question ? (
                    <Tooltip title={scannerName}>
                        <span>{observation.prompt_question}</span>
                    </Tooltip>
                ) : (
                    <span className="text-muted">{scannerName}</span>
                )}
            </p>
            {scannerType !== 'summarizer' && <ObservationResultSummary observation={observation} />}
        </div>
    )
}

export function WatchFeedCard({ item, position }: WatchFeedCardProps): JSX.Element {
    const { observation, reason } = item
    const {
        keyMomentMs,
        scannerType,
        scannerName,
        person,
        headline,
        observationUrl,
        captureObservationOpened,
        watchClipInModal,
    } = useWatchFeedCardData(item, position, 'list')

    return (
        <div
            className="@container relative border rounded bg-bg-light p-4 flex gap-4 hover:border-accent"
            data-attr="vision-watch-feed-card"
        >
            {!observation.viewed && <span className="absolute inset-y-0 left-0 w-1 rounded-l bg-accent" aria-hidden />}
            {/* The thumbnail is the watch affordance, so the whole poster opens the clip modal.
                The New tag and the key moment sit outside the poster, which clips its own overflow. */}
            <div className="relative hidden @md:block w-64 shrink-0 self-start">
                <WatchClipPoster observation={observation} keyMomentMs={keyMomentMs} onWatch={watchClipInModal} />
                {/* Sits above the button, so it lets clicks through to open the clip. */}
                {!observation.viewed && (
                    <UnviewedObservationTag className="absolute top-1 left-1 z-10 pointer-events-none" />
                )}
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                {/* Stretched to cover the card: clicking anywhere opens the observation with the
                    player expanded. Inner links and the thumbnail button sit above it via
                    `relative z-10`, so the anchors never nest. */}
                <Link
                    to={observationUrl}
                    onClick={captureObservationOpened}
                    className="text-default after:absolute after:inset-0 after:content-['']"
                    data-attr="vision-watch-feed-card-body"
                >
                    <h3 className="text-sm font-semibold m-0 line-clamp-2">
                        {/* The tag hides with the thumbnail on narrow cards, so screen readers get it here. */}
                        {!observation.viewed && <span className="sr-only">New: </span>}
                        {headline?.title ?? scannerName}
                    </h3>
                </Link>
                <WatchCardPerson observation={observation} person={person} />
                <WatchCardScanner observation={observation} scannerType={scannerType} scannerName={scannerName} />
                {headline?.body && (
                    <p className="text-muted text-xs m-0 line-clamp-2">
                        <CitedText text={headline.body.text} segments={headline.body.segments} />
                    </p>
                )}
                <div className="flex items-start gap-1.5 text-xs font-medium border-t pt-2">
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

/**
 * The one sentence a jev-arm card leads with. The scan's notability sentence names the finding, so
 * it outranks prose derived from the result; the derived headline covers scans from before
 * notability shipped, and the scanner's name covers scans with no prose at all.
 */
export function jevCardSentence(observation: ReplayObservationApi, reason: WatchFeedReasonApi): string {
    if (reason.notability_reason) {
        return reason.notability_reason
    }
    const headline = watchCardHeadline(observation)
    return headline?.title ?? ((observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)')
}

/**
 * One muted line of context under the sentence: the scan's prose the sentence did not use. A card
 * leading with the notability sentence gets the whole derived narration; a card already leading
 * with the derived headline gets the prose after it. A filler row gets none, so it stays small.
 */
export function jevCardContext(observation: ReplayObservationApi, reason: WatchFeedReasonApi): string | null {
    if (FILLER_REASON_KINDS.has(reason.kind)) {
        return null
    }
    const headline = watchCardHeadline(observation)
    if (reason.notability_reason) {
        return [headline?.title, headline?.body?.text].filter(Boolean).join(' ') || null
    }
    return headline?.body?.text ?? null
}

function JevCardScannerChip({
    observation,
    scannerName,
}: {
    observation: ReplayObservationApi
    scannerName: string
}): JSX.Element {
    const { setScannerIdsFilter } = useActions(watchFeedLogic)
    const verdict = readResult(observation)?.verdict
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-0.5">
                    <span className="font-semibold">{scannerName}</span>
                    {observation.prompt_question && (
                        <span>
                            {observation.prompt_question}
                            {typeof verdict === 'string' && verdict ? ` Answered ${verdict}.` : ''}
                        </span>
                    )}
                    <span className="italic">Click to show only this scanner's clips</span>
                </div>
            }
        >
            <LemonTag
                className="max-w-60 cursor-pointer"
                forceClickable
                onClick={() => setScannerIdsFilter([observation.scanner_id])}
                data-attr="vision-watch-feed-scanner-chip"
            >
                <span className="truncate">{scannerName}</span>
            </LemonTag>
        </Tooltip>
    )
}

/** The jev arm's card body: one sentence plus one meta line. The scanner's question, verdict, and
 * remaining prose sit behind the chip's tooltip and the observation page, so the feed stays scannable. */
function JevCardBody({ item, data }: { item: WatchFeedItemApi; data: WatchFeedCardData }): JSX.Element {
    const { observation, reason } = item
    // A filler row carries no finding, so it must not read like one.
    const filler = FILLER_REASON_KINDS.has(reason.kind)
    const context = jevCardContext(observation, reason)
    return (
        <>
            <Link
                to={data.observationUrl}
                onClick={data.captureObservationOpened}
                className="text-default after:absolute after:inset-0 after:content-['']"
                data-attr="vision-watch-feed-card-body"
            >
                <h3 className={`text-sm m-0 line-clamp-2 ${filler ? 'font-medium text-secondary' : 'font-semibold'}`}>
                    {!observation.viewed && <span className="sr-only">New: </span>}
                    {jevCardSentence(observation, reason)}
                </h3>
            </Link>
            {context && <p className="text-muted text-xs m-0 line-clamp-1">{context}</p>}
            <div className="relative z-10 flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
                <JevCardScannerChip observation={observation} scannerName={data.scannerName} />
                <WatchCardPerson observation={observation} person={data.person} />
            </div>
        </>
    )
}

/** The jev arm's list card. Same shell and affordances as WatchFeedCard, with the body cut to
 * JevCardBody's three lines and the poster sized down so the card hugs its content. */
export function JevWatchFeedCard({ item, position }: WatchFeedCardProps): JSX.Element {
    const { observation } = item
    const data = useWatchFeedCardData(item, position, 'list')
    return (
        <div
            className="@container relative border rounded bg-bg-light p-3 flex gap-3 hover:border-accent"
            data-attr="vision-watch-feed-card"
        >
            {!observation.viewed && <span className="absolute inset-y-0 left-0 w-1 rounded-l bg-accent" aria-hidden />}
            <div className="relative hidden @md:block w-44 shrink-0 self-start">
                <WatchClipPoster
                    observation={observation}
                    keyMomentMs={data.keyMomentMs}
                    onWatch={data.watchClipInModal}
                />
                {!observation.viewed && (
                    <UnviewedObservationTag className="absolute top-1 left-1 z-10 pointer-events-none" />
                )}
            </div>
            <div className="flex-1 min-w-0 flex flex-col justify-center gap-1.5">
                <JevCardBody item={item} data={data} />
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={<IconPlay />}
                    onClick={data.watchClipInModal}
                    className="@md:hidden self-start relative z-10"
                    data-attr="vision-watch-clip"
                >
                    Watch clip
                </LemonButton>
            </div>
        </div>
    )
}

/** The jev arm's grid card: the same shell as WatchFeedGridCard with the body cut to two lines. */
export function JevWatchFeedGridCard({ item, position }: WatchFeedCardProps): JSX.Element {
    const { observation } = item
    const data = useWatchFeedCardData(item, position, 'grid')
    return (
        <LemonCard
            className="relative flex flex-col rounded-lg p-0 overflow-hidden hover:border-accent"
            data-attr="vision-watch-feed-grid-card"
        >
            {!observation.viewed && <span className="absolute inset-x-0 top-0 h-1 z-20 bg-accent" aria-hidden />}
            <div className="relative">
                <WatchClipPoster
                    observation={observation}
                    keyMomentMs={data.keyMomentMs}
                    onWatch={data.watchClipInModal}
                    className="rounded-none border-0"
                />
                {!observation.viewed && (
                    <UnviewedObservationTag className="absolute top-2 left-2 z-10 pointer-events-none" />
                )}
            </div>
            <div className="flex flex-col gap-2 p-3 min-w-0 flex-1">
                <JevCardBody item={item} data={data} />
            </div>
        </LemonCard>
    )
}

/** The thumbnail-first layout for the grid view, with the feed's reason as its own closing section. */
export function WatchFeedGridCard({ item, position }: WatchFeedCardProps): JSX.Element {
    const { observation, reason } = item
    const {
        keyMomentMs,
        scannerType,
        scannerName,
        person,
        headline,
        observationUrl,
        captureObservationOpened,
        watchClipInModal,
    } = useWatchFeedCardData(item, position, 'grid')

    return (
        <LemonCard
            className="relative flex flex-col rounded-lg p-0 overflow-hidden hover:border-accent"
            data-attr="vision-watch-feed-grid-card"
        >
            {!observation.viewed && <span className="absolute inset-x-0 top-0 h-1 z-20 bg-accent" aria-hidden />}
            {/* The card clips its own corners and draws its own edge, so the poster goes edge to edge. */}
            <div className="relative">
                <WatchClipPoster
                    observation={observation}
                    keyMomentMs={keyMomentMs}
                    onWatch={watchClipInModal}
                    className="rounded-none border-0"
                />
                {!observation.viewed && (
                    <UnviewedObservationTag className="absolute top-2 left-2 z-10 pointer-events-none" />
                )}
            </div>
            <div className="flex flex-col gap-1.5 p-3 min-w-0 flex-1">
                {/* Stretched over the card like the list card, so a click outside the poster and inner
                    links opens the observation. */}
                <Link
                    to={observationUrl}
                    onClick={captureObservationOpened}
                    className="text-default after:absolute after:inset-0 after:content-['']"
                    data-attr="vision-watch-feed-card-body"
                >
                    <h3 className="text-sm font-semibold m-0 line-clamp-2">
                        {!observation.viewed && <span className="sr-only">New: </span>}
                        {headline?.title ?? scannerName}
                    </h3>
                </Link>
                <WatchCardPerson observation={observation} person={person} />
                <WatchCardScanner observation={observation} scannerType={scannerType} scannerName={scannerName} />
                {headline?.body && (
                    <p className="text-muted text-xs m-0 line-clamp-2">
                        <CitedText text={headline.body.text} segments={headline.body.segments} />
                    </p>
                )}
                <div className="mt-auto flex flex-col gap-1 border-t pt-2" data-attr="vision-watch-feed-why">
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-muted">
                        <IconFlag className="shrink-0 text-accent" aria-hidden />
                        Why this recording
                    </span>
                    <span className="text-xs">{watchReasonCopy(reason)}</span>
                </div>
            </div>
        </LemonCard>
    )
}
