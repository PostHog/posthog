import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconFlag, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { useAutoMarkRead } from 'lib/components/NotificationsMenu/useAutoMarkRead'
import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { readResult } from '../../components/ObservationCard'
import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { scannerTypeIcon } from '../../components/ScannerTypeBadge'
import { UnviewedObservationTag } from '../../components/UnviewedObservationTag'
import type {
    JevWatchReasonEnumApi,
    ReplayObservationApi,
    WatchFeedCategoryEnumApi,
    WatchFeedItemApi,
    WatchFeedReasonApi,
} from '../../generated/api.schemas'
import { OBSERVATION_ORIGIN_PARAM, WATCH_FEED_ORIGIN } from '../../utils/breadcrumbs'
import { citedTextToPlainText } from '../../utils/citations'
import { hasScannerPage, scannerLabel } from '../../utils/observation'
import { SCANNER_TYPE_TAG_TYPE, ScannerType } from '../types'
import { watchFeedLogic } from '../watchFeedLogic'
import { CARD_SEEN_DWELL_MS, cardProperties } from '../watchFeedTelemetry'
import { WatchFeedDismissButton } from './WatchFeedDismissButton'

/** Reason kinds that say nothing about the session. The backend returns these only to pad a near-empty
 * feed, so a feed made up entirely of them means the window turned up no findings at all. */
export const FILLER_REASON_KINDS = new Set(['unviewed_recent', 'recent'])

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

const WATCH_CATEGORY_COPY: Record<WatchFeedCategoryEnumApi, string> = {
    failure: 'Something failed in this session.',
    struggle: 'The user struggled in this session.',
    revenue: 'This session touches billing or a plan limit.',
}

/** What the reason kind says about the session. Never the scan's notability sentence: the row's title
 * already leads with it. */
export function watchReasonCopy(reason: WatchFeedReasonApi): string {
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
        case 'embedding_pick': {
            const category = reason.watch_category
                ? WATCH_CATEGORY_COPY[reason.watch_category]
                : 'This session stands out for this scanner.'
            const similar = reason.similar_count ?? 0
            if (similar === 0) {
                return category
            }
            return `${category} ${similar} other session${similar === 1 ? ' from this scanner looks' : 's from this scanner look'} similar.`
        }
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

interface WatchFeedRowProps {
    item: WatchFeedItemApi
    /** Zero-based place in the feed, captured so we can see how deep people read. */
    position: number
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

/**
 * The one sentence a row leads with when the scan wrote no short title. The scan's notability
 * sentence names the finding, so it outranks prose derived from the result; the derived headline
 * covers scans from before notability shipped, and the scanner's name covers scans with no prose at all.
 */
export function watchFeedRowSentence(observation: ReplayObservationApi, reason: WatchFeedReasonApi): string {
    if (reason.notability_reason) {
        return reason.notability_reason
    }
    const headline = watchCardHeadline(observation)
    return headline?.title ?? scannerLabel(observation)
}

/**
 * The scanner behind a row: a circle in its type's color, then its name. Clicking it opens the
 * scanner. The tooltip carries the scanner's question and verdict.
 */
function WatchFeedScannerLink({
    observation,
    scannerName,
    scannerType,
}: {
    observation: ReplayObservationApi
    scannerName: string
    scannerType: ScannerType | undefined
}): JSX.Element {
    const verdict = readResult(observation)?.verdict
    const linked = hasScannerPage(observation)
    const chip = (
        <>
            {scannerType && (
                <LemonTag
                    type={SCANNER_TYPE_TAG_TYPE[scannerType]}
                    className="size-6 shrink-0 justify-center !rounded-full !p-0"
                >
                    {scannerTypeIcon(scannerType)}
                </LemonTag>
            )}
            <span className="truncate font-medium">{scannerName}</span>
        </>
    )
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
                    {linked && <span className="italic">Click to open this scanner</span>}
                </div>
            }
        >
            {/* A one-off scan has no scanner page, so its chip names the scan without linking anywhere. */}
            {linked ? (
                <Link
                    to={urls.replayVision(observation.scanner_id)}
                    subtle
                    className="relative z-10 flex max-w-full min-w-0 items-center gap-2 self-start text-sm text-secondary hover:text-default"
                    data-attr="vision-watch-feed-scanner-chip"
                >
                    {chip}
                </Link>
            ) : (
                <span className="relative z-10 flex max-w-full min-w-0 items-center gap-2 self-start text-sm text-secondary">
                    {chip}
                </span>
            )}
        </Tooltip>
    )
}

/** The sentence that says why a row was picked, for each reason Jev can pick from its fixed list. */
const JEV_WATCH_REASON_COPY: Record<JevWatchReasonEnumApi, string> = {
    visible_error: 'The user saw an error message or a failed action in this session.',
    silent_failure: "Something the user did didn't take effect, and nothing told them.",
    unresponsive: "The user clicked on something that didn't respond.",
    slow_or_stuck: 'The page was slow to load or got stuck while the user waited.',
    blocked: "The user hit a dead end they couldn't get past.",
    cant_find: "The user searched for something and couldn't find it.",
    confused: 'The user seemed unsure how something worked and went back and forth.',
    workaround: 'The user gave up on the usual path and found another way to finish.',
    abandoned: 'The user started a task and left without finishing it.',
    churn_signal: 'The user showed signs of churn or downgrading in this session.',
    success: 'The user reached their goal smoothly, a good example of the product working.',
}

/** Why a row was picked: Jev's pick when it gave one, otherwise what the reason kind says, so both
 * ranker arms explain each row. */
export function watchFeedRowWhy(reason: WatchFeedReasonApi): string {
    // A value this build does not know (the backend list grew first) falls back to the kind's copy.
    return (reason.watch_reason && JEV_WATCH_REASON_COPY[reason.watch_reason]) || watchReasonCopy(reason)
}

/**
 * The title of a row. A summarizer's authored title is already short, so it leads. Other scans
 * lead with watchFeedRowSentence.
 */
export function watchFeedRowTitle(observation: ReplayObservationApi, reason: WatchFeedReasonApi): string {
    const result = readResult(observation)
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    if (scannerType === 'summarizer' && typeof result?.title === 'string' && result.title) {
        return result.title
    }
    return watchFeedRowSentence(observation, reason)
}

/**
 * One feed row, laid out as a post: who and where on top, then the title and the reason it was
 * picked, then the key-moment poster and a button that starts the player there. Every ranker arm
 * renders it, so the experiment compares rankings, not layouts. The whole card opens the
 * observation page.
 */
export function WatchFeedRow({ item, position }: WatchFeedRowProps): JSX.Element {
    const { observation, reason } = item
    const { feedLoad } = useValues(watchFeedLogic)
    const { cardSeen, dismissItem } = useActions(watchFeedLogic)
    const rowRef = useAutoMarkRead(true, () => cardSeen(item, position), CARD_SEEN_DWELL_MS)
    const result = readResult(observation)
    // Fall back to the result's own scanner_type when the snapshot is absent, like watchCardHeadline.
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    const scannerName = scannerLabel(observation)
    const person = observation.recording_subject_email || observation.distinct_id
    const keyMomentMs = observationKeyMomentMs(observation)
    // `t` is always set, so the observation page opens with the player expanded. `from` marks the feed as
    // the origin, so the observation's back button returns here rather than the scanner.
    const observationUrl = combineUrl(urls.replayVisionObservation(observation.id), {
        t: watchStartSeconds(keyMomentMs),
        [OBSERVATION_ORIGIN_PARAM]: WATCH_FEED_ORIGIN,
    }).url
    const title = watchFeedRowTitle(observation, reason)
    const filler = FILLER_REASON_KINDS.has(reason.kind)
    const captureOpened = (): void => {
        posthog.capture('replay_vision_watch_clip_clicked', {
            ...cardProperties(feedLoad, item, position, 'feed_tab'),
            scanner_type: scannerType,
            has_key_moment: keyMomentMs !== null,
            target: 'observation',
        })
    }
    return (
        <article
            ref={rowRef}
            className="group relative flex min-w-0 flex-col gap-3 rounded-lg border bg-surface-primary p-4 hover:border-accent focus-within:border-accent"
            data-attr="vision-watch-feed-row"
        >
            <header className="flex min-w-0 items-center gap-2">
                <WatchFeedScannerLink observation={observation} scannerName={scannerName} scannerType={scannerType} />
                <span className="text-xs text-muted" aria-hidden>
                    ·
                </span>
                <div className="min-w-0 flex-1">
                    <WatchCardPerson observation={observation} person={person} />
                </div>
                <WatchFeedDismissButton
                    className="relative z-10 shrink-0"
                    onDismiss={(dismissalReason) => dismissItem(item, position, dismissalReason)}
                />
            </header>
            <div className="flex min-w-0 flex-col gap-1">
                <Link
                    to={observationUrl}
                    onClick={captureOpened}
                    className="text-default after:absolute after:inset-0 after:content-['']"
                    data-attr="vision-watch-feed-row-open"
                >
                    <h3
                        className={`m-0 text-base line-clamp-2 group-hover:text-accent ${filler ? 'font-medium text-secondary' : 'font-semibold'}`}
                        title={title}
                    >
                        {!observation.viewed && <span className="sr-only">New: </span>}
                        {title}
                    </h3>
                </Link>
                <p className="m-0 flex items-start gap-1.5 text-sm text-secondary" data-attr="vision-watch-feed-why">
                    <Tooltip title="Why this recording">
                        <span className="mt-0.5 flex shrink-0">
                            <IconFlag className="text-accent" aria-hidden />
                        </span>
                    </Tooltip>
                    <span className="line-clamp-3">
                        <span className="sr-only">Why this recording: </span>
                        {watchFeedRowWhy(reason)}
                    </span>
                </p>
            </div>
            {/* Clicks pass through the poster to the card's link, which sits beneath it. */}
            <div className="pointer-events-none relative overflow-hidden rounded-md border">
                {!observation.viewed && <span className="absolute inset-x-0 top-0 z-20 h-1 bg-accent" aria-hidden />}
                <ObservationThumbnail observation={observation} className="rounded-none border-0" />
                {!observation.viewed && <UnviewedObservationTag className="absolute top-2 left-2 z-10" />}
            </div>
            <footer className="flex items-center gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlayFilled />}
                    to={observationUrl}
                    onClick={captureOpened}
                    className="relative z-10"
                    data-attr="vision-watch-feed-row-watch"
                >
                    {keyMomentMs !== null
                        ? `Watch from ${colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null)}`
                        : 'Watch session'}
                </LemonButton>
            </footer>
        </article>
    )
}
