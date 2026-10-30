import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconFlag, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { useAutoMarkRead } from 'lib/components/NotificationsMenu/useAutoMarkRead'
import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { readResult } from '../../components/ObservationCard'
import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { scannerTypeIcon } from '../../components/ScannerTypeBadge'
import { UnviewedObservationTag } from '../../components/UnviewedObservationTag'
import type {
    ReplayObservationApi,
    HighlightFeedCategoryEnumApi,
    HighlightFeedItemApi,
    HighlightFeedReasonApi,
} from '../../generated/api.schemas'
import { OBSERVATION_ORIGIN_PARAM, HIGHLIGHT_FEED_ORIGIN } from '../../utils/breadcrumbs'
import { citedTextToPlainText } from '../../utils/citations'
import { hasScannerPage, scannerLabel } from '../../utils/observation'
import { feedCategoriesParam, highlightFeedLogic } from '../highlightFeedLogic'
import { CARD_SEEN_DWELL_MS, cardProperties } from '../highlightFeedTelemetry'
import { SCANNER_TYPE_TAG_TYPE, ScannerType } from '../types'
import { HighlightFeedDismissButton } from './HighlightFeedDismissButton'
import { HighlightFeedGroupToggle, similarSessionsLabel } from './HighlightFeedGroup'

/** Reason kinds that say nothing about the session. The backend returns these only to pad a near-empty
 * feed, so a feed made up entirely of them means the window turned up no findings at all. */
export const FILLER_REASON_KINDS = new Set(['unviewed_recent', 'recent'])

const WATCH_CATEGORY_COPY: Record<
    HighlightFeedCategoryEnumApi,
    { alone: string; withSimilar: (similar: string) => string }
> = {
    failure: {
        alone: 'Something failed in this session.',
        withSimilar: (similar) => `Something failed here and in ${similar}.`,
    },
    struggle: {
        alone: 'The user struggled in this session.',
        withSimilar: (similar) => `The user struggled here and in ${similar}.`,
    },
    revenue: {
        alone: 'A payment problem came up in this session.',
        withSimilar: (similar) => `A payment problem came up here and in ${similar}.`,
    },
}

/** What the reason kind says about the session. */
export function highlightReasonCopy(reason: HighlightFeedReasonApi): string {
    switch (reason.kind) {
        case 'embedding_pick': {
            // Sessions, not people, so the count matches the card's similar sessions button.
            const similar = reason.similar_count ?? 0
            const copy = reason.watch_category ? WATCH_CATEGORY_COPY[reason.watch_category] : null
            if (similar === 0) {
                return copy?.alone ?? 'This session stands out for this scanner.'
            }
            return copy
                ? copy.withSimilar(similarSessionsLabel(similar))
                : `This session and ${pluralize(similar, 'similar one')} stand out for this scanner.`
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
export function highlightStartSeconds(keyMomentMs: number | null): number {
    return keyMomentMs === null ? 0 : Math.max(0, Math.floor(keyMomentMs / 1000) - KEY_MOMENT_LEAD_IN_S)
}

/** The observation page. `t` is always set, so the player opens expanded, and `from` makes the back button return to the feed. */
export function highlightFeedObservationUrl(observation: ReplayObservationApi): string {
    return combineUrl(urls.replayVisionObservation(observation.id), {
        t: highlightStartSeconds(observationKeyMomentMs(observation)),
        [OBSERVATION_ORIGIN_PARAM]: HIGHLIGHT_FEED_ORIGIN,
    }).url
}

/**
 * The card's bold headline, plus the prose that follows it. A summarizer authored a title, so its
 * summary rides along whole (with citation chips). Otherwise the first sentence of the prose the
 * scan wrote (an untitled summarizer's summary, the other types' reasoning) is promoted to the
 * headline, with citation chips rendered as plain timestamps so a mid-sentence citation keeps
 * its place, and the rest becomes the body, already plain.
 */
export function highlightCardHeadline(
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

interface HighlightFeedRowProps {
    item: HighlightFeedItemApi
    /** Zero-based place in the feed, captured so we can see how deep people read. */
    position: number
}

function HighlightCardPerson({
    observation,
    person,
}: {
    observation: ReplayObservationApi
    person: string | null | undefined
}): JSX.Element {
    return (
        <div className="flex min-w-0 items-center gap-1 text-xs text-muted">
            {person &&
                (observation.distinct_id ? (
                    <Link
                        to={urls.personByDistinctId(observation.distinct_id)}
                        className="relative z-10 truncate min-w-0 text-muted"
                        data-attr="vision-highlight-feed-person"
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

/** The one sentence a row leads with when the scan wrote no short title, or the scanner's name for scans with no prose at all. */
export function highlightFeedRowSentence(observation: ReplayObservationApi): string {
    const headline = highlightCardHeadline(observation)
    return headline?.title ?? scannerLabel(observation)
}

/**
 * The scanner behind a row: a circle in its type's color, then its name. Clicking it opens the
 * scanner. The tooltip carries the scanner's question and verdict.
 */
function HighlightFeedScannerLink({
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
                    data-attr="vision-highlight-feed-scanner-chip"
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

/**
 * The title of a row. A summarizer's authored title is already short, so it leads. Other scans
 * lead with highlightFeedRowSentence.
 */
export function highlightFeedRowTitle(observation: ReplayObservationApi): string {
    const result = readResult(observation)
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    if (scannerType === 'summarizer' && typeof result?.title === 'string' && result.title) {
        return result.title
    }
    return highlightFeedRowSentence(observation)
}

/**
 * One feed row, laid out as a post: who and where on top, then the title and the reason it was
 * picked, then the key-moment poster and a button that starts the player there. The whole card
 * opens the observation page.
 */
export function HighlightFeedRow({ item, position }: HighlightFeedRowProps): JSX.Element {
    const { observation, reason } = item
    const { feedLoad, feedReloading, dateFrom, categories } = useValues(highlightFeedLogic)
    const { cardSeen, dismissItem } = useActions(highlightFeedLogic)
    // Re-armed per feed load, so a card kept across a reload counts toward the new load.
    const rowRef = useAutoMarkRead(
        !feedReloading,
        () => cardSeen(item, position),
        CARD_SEEN_DWELL_MS,
        feedLoad?.feedLoadId
    )
    const result = readResult(observation)
    // Fall back to the result's own scanner_type when the snapshot is absent, like highlightCardHeadline.
    const scannerType =
        (observation.scanner_snapshot?.scanner_type as ScannerType | undefined) ??
        (result?.scanner_type as ScannerType | undefined)
    const scannerName = scannerLabel(observation)
    const person = observation.recording_subject_email || observation.distinct_id
    const keyMomentMs = observationKeyMomentMs(observation)
    const observationUrl = highlightFeedObservationUrl(observation)
    const title = highlightFeedRowTitle(observation)
    const why = highlightReasonCopy(reason)
    const filler = FILLER_REASON_KINDS.has(reason.kind)
    const similarCount = reason.kind === 'embedding_pick' ? (reason.similar_count ?? 0) : 0
    const groupProps = {
        observationId: observation.id,
        scannerId: observation.scanner_id,
        dateFrom,
        categories: feedCategoriesParam(categories),
        similarCount,
        affectedPeople: reason.kind === 'embedding_pick' ? (reason.affected_people ?? null) : null,
        cardContext: cardProperties(feedLoad, item, position, 'feed_tab'),
    }
    const captureOpened = (): void => {
        posthog.capture('replay_vision_highlight_clip_clicked', {
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
            data-attr="vision-highlight-feed-row"
        >
            <header className="flex min-w-0 items-center gap-2">
                <div className="flex min-w-0">
                    <HighlightFeedScannerLink
                        observation={observation}
                        scannerName={scannerName}
                        scannerType={scannerType}
                    />
                </div>
                <span className="text-xs text-muted" aria-hidden>
                    ·
                </span>
                {/* The person and age keep up to 45% of the line, so a long email is cut before the scanner name. */}
                <div className="min-w-0 max-w-[45%] shrink-0">
                    <HighlightCardPerson observation={observation} person={person} />
                </div>
                <HighlightFeedDismissButton
                    className="relative z-10 ml-auto shrink-0"
                    onDismiss={(dismissalReason) => dismissItem(item, position, dismissalReason)}
                />
            </header>
            <div className="flex min-w-0 flex-col gap-1">
                <Link
                    to={observationUrl}
                    onClick={captureOpened}
                    className="text-default after:absolute after:inset-0 after:content-['']"
                    data-attr="vision-highlight-feed-row-open"
                >
                    <h3
                        // Two lines are always reserved, so cards in one grid row keep their posters level.
                        className={`m-0 min-h-[2lh] text-base line-clamp-2 wrap-anywhere group-hover:text-accent ${filler ? 'font-medium text-secondary' : 'font-semibold'}`}
                        title={title}
                    >
                        {!observation.viewed && <span className="sr-only">New: </span>}
                        {title}
                    </h3>
                </Link>
                <p
                    className="m-0 flex items-start gap-1.5 text-sm text-secondary"
                    data-attr="vision-highlight-feed-why"
                >
                    <Tooltip title="Why this recording">
                        <span className="mt-0.5 flex shrink-0">
                            <IconFlag className="text-accent" aria-hidden />
                        </span>
                    </Tooltip>
                    <span className="min-w-0 truncate" title={why}>
                        <span className="sr-only">Why this recording: </span>
                        {why}
                    </span>
                </p>
            </div>
            {/* Clicks pass through the poster to the card's link, which sits beneath it. */}
            <div className="pointer-events-none relative overflow-hidden rounded-md border">
                {!observation.viewed && <span className="absolute inset-x-0 top-0 z-20 h-1 bg-accent" aria-hidden />}
                <ObservationThumbnail
                    observation={observation}
                    className="rounded-none border-0"
                    retryKey={feedLoad?.feedLoadId}
                />
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
                    data-attr="vision-highlight-feed-row-watch"
                >
                    {keyMomentMs !== null
                        ? `Watch from ${colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null)}`
                        : 'Watch session'}
                </LemonButton>
                {similarCount > 0 && <HighlightFeedGroupToggle {...groupProps} />}
            </footer>
        </article>
    )
}
