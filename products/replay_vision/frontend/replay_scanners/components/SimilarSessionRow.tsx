import { IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { UnviewedObservationTag } from '../../components/UnviewedObservationTag'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import { citedTextToPlainText } from '../../utils/citations'
import { isSummaryScannerType, scannerLabel } from '../../utils/observation'
import { highlightCardHeadline, highlightFeedObservationUrl, observationKeyMomentMs } from './HighlightFeedCard'
import { ObservationRowResult } from './ObservationRowResult'

/**
 * One session in a feed group, with the scan's headline, its reasoning, and its answer, so a reader can
 * compare sessions without opening each one.
 */
export function SimilarSessionRow({
    observation,
    groupObservationId,
}: {
    observation: ReplayObservationApi
    /** The card's observation, which the page was opened from. */
    groupObservationId: string
}): JSX.Element {
    const url = highlightFeedObservationUrl(observation)
    const keyMomentMs = observationKeyMomentMs(observation)
    const headline = highlightCardHeadline(observation)
    const title = headline?.title ?? scannerLabel(observation)
    const body = headline?.body ? citedTextToPlainText(headline.body.text, headline.body.segments) : null
    const person = observation.recording_subject_email || observation.distinct_id
    const isGroupObservation = observation.id === groupObservationId
    // A summary's text is already the headline and body, so only other scans add an answer line.
    const showAnswer = !isSummaryScannerType(observation.scanner_snapshot?.scanner_type)
    const captureOpened = (target: string) => (): void => {
        posthog.capture('replay_vision_similar_sessions_member_opened', {
            observation_id: groupObservationId,
            member_observation_id: observation.id,
            is_group_observation: isGroupObservation,
            target,
        })
    }
    return (
        <li
            className="flex min-w-0 flex-col gap-3 rounded-lg border bg-surface-primary p-3 @2xl/similar-sessions:flex-row"
            data-attr="vision-similar-sessions-row"
        >
            <Link
                to={url}
                className="relative w-full shrink-0 self-start overflow-hidden rounded border border-primary @2xl/similar-sessions:w-64"
                onClick={captureOpened('thumbnail')}
            >
                <ObservationThumbnail observation={observation} className="rounded-none border-0" />
                {!observation.viewed && <UnviewedObservationTag className="absolute top-1 left-1" />}
            </Link>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex min-w-0 items-start gap-2">
                    <Link
                        to={url}
                        className="line-clamp-2 font-semibold wrap-anywhere text-default"
                        title={title}
                        onClick={captureOpened('title')}
                    >
                        {title}
                    </Link>
                    {isGroupObservation && (
                        <LemonTag type="muted" className="shrink-0">
                            Opened from the feed
                        </LemonTag>
                    )}
                </div>
                {body && <p className="m-0 line-clamp-3 text-sm text-secondary">{body}</p>}
                {showAnswer && (
                    <div className="min-w-0 [&_.truncate]:line-clamp-2 [&_.truncate]:whitespace-normal">
                        <ObservationRowResult observation={observation} />
                    </div>
                )}
                <div className="flex min-w-0 flex-wrap items-center gap-x-1 text-xs text-muted">
                    {person && <span className="truncate">{person}</span>}
                    {person && <span aria-hidden>·</span>}
                    <TZLabel time={observation.created_at} className="shrink-0" />
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlayFilled />}
                    to={url}
                    onClick={captureOpened('watch')}
                    className="mt-1 self-start"
                    data-attr="vision-similar-sessions-watch"
                >
                    {keyMomentMs !== null
                        ? `Watch from ${colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null)}`
                        : 'Watch session'}
                </LemonButton>
            </div>
        </li>
    )
}
