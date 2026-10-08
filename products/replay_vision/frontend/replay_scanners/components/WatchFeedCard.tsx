import { useActions } from 'kea'
import { combineUrl } from 'kea-router'

import { IconFlag } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

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
    WatchFeedItemApi,
    WatchFeedReasonApi,
} from '../../generated/api.schemas'
import { OBSERVATION_ORIGIN_PARAM, WATCH_FEED_ORIGIN } from '../../utils/breadcrumbs'
import { citedTextToPlainText } from '../../utils/citations'
import { SCANNER_TYPE_TAG_TYPE, ScannerType } from '../types'
import { watchFeedLogic } from '../watchFeedLogic'

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
    return headline?.title ?? ((observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)')
}

/**
 * The scanner behind a row: a circle in its type's color, then its name. Clicking it narrows the
 * feed to that scanner. The tooltip carries the scanner's question and verdict.
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
                    <span className="italic">Click to show only this scanner's sessions</span>
                </div>
            }
        >
            <button
                type="button"
                onClick={() => setScannerIdsFilter([observation.scanner_id])}
                className="relative z-10 flex max-w-full min-w-0 cursor-pointer items-center gap-2 self-start text-sm text-secondary hover:text-default"
                data-attr="vision-watch-feed-scanner-chip"
            >
                {scannerType && (
                    <LemonTag
                        type={SCANNER_TYPE_TAG_TYPE[scannerType]}
                        className="size-6 shrink-0 justify-center !rounded-full !p-0"
                    >
                        {scannerTypeIcon(scannerType)}
                    </LemonTag>
                )}
                <span className="truncate font-medium">{scannerName}</span>
            </button>
        </Tooltip>
    )
}

/** The sentence after "Why this recording:" for each reason Jev can pick from its fixed list. */
const JEV_WATCH_REASON_COPY: Record<JevWatchReasonEnumApi, string> = {
    visible_error: 'the user saw an error message or a failed action in this session.',
    silent_failure: "something the user did didn't take effect, and nothing told them.",
    unresponsive: "the user clicked on something that didn't respond.",
    slow_or_stuck: 'the page was slow to load or got stuck while the user waited.',
    blocked: "the user hit a dead end they couldn't get past.",
    cant_find: "the user searched for something and couldn't find it.",
    confused: 'the user seemed unsure how something worked and went back and forth.',
    workaround: 'the user gave up on the usual path and found another way to finish.',
    abandoned: 'the user started a task and left without finishing it.',
    churn_signal: 'the user showed signs of churn or downgrading in this session.',
    success: 'the user reached their goal smoothly, a good example of the product working.',
}

/** The sentence after "Why this recording:": Jev's pick when it gave one, otherwise what the reason kind
 * says, so both ranker arms explain each row. */
export function watchFeedRowWhy(reason: WatchFeedReasonApi): string {
    // A value this build does not know (the backend list grew first) falls back to the kind's copy.
    const copy = (reason.watch_reason && JEV_WATCH_REASON_COPY[reason.watch_reason]) || watchReasonCopy(reason)
    return copy.charAt(0).toLowerCase() + copy.slice(1)
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
 * One feed row, laid out like a video search result: a large key-moment poster, then a title, the
 * reason Jev picked the session when it gave one, the scanner, and the person and time. Both ranker
 * arms render it, so the experiment compares rankings, not layouts. The whole row opens the
 * observation page, which starts the player at the key moment.
 */
export function WatchFeedRow({ item, position }: WatchFeedRowProps): JSX.Element {
    const { observation, reason } = item
    const result = readResult(observation)
    // Fall back to the result's own scanner_type when the snapshot is absent, like watchCardHeadline.
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    const scannerName = (observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)'
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
            scanner_id: observation.scanner_id,
            scanner_type: scannerType,
            observation_id: observation.id,
            position,
            reason_kind: reason.kind,
            has_key_moment: keyMomentMs !== null,
            target: 'observation',
        })
    }
    return (
        <article className="group relative flex min-w-0 gap-4" data-attr="vision-watch-feed-row">
            <div className="relative w-36 shrink-0 self-start overflow-hidden rounded-lg border group-hover:border-accent group-focus-within:border-accent @xl:w-80">
                {!observation.viewed && <span className="absolute inset-x-0 top-0 z-20 h-1 bg-accent" aria-hidden />}
                <ObservationThumbnail observation={observation} className="rounded-none border-0" />
                {!observation.viewed && (
                    <UnviewedObservationTag className="absolute top-2 left-2 z-10 pointer-events-none" />
                )}
                {keyMomentMs !== null && (
                    <span className="absolute bottom-2 right-2 z-10 rounded bg-black/70 px-1.5 text-xs tabular-nums text-white">
                        {colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null)}
                    </span>
                )}
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-2 pt-0.5">
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
                <WatchFeedScannerLink observation={observation} scannerName={scannerName} scannerType={scannerType} />
                <WatchCardPerson observation={observation} person={person} />
                <p
                    className="m-0 mt-1 flex items-start gap-1.5 border-t pt-2 text-sm text-secondary"
                    data-attr="vision-watch-feed-why"
                >
                    <IconFlag className="mt-0.5 shrink-0 text-accent" aria-hidden />
                    <span className="line-clamp-2">
                        <span className="font-medium text-default">Why this recording:</span> {watchFeedRowWhy(reason)}
                    </span>
                </p>
            </div>
        </article>
    )
}
