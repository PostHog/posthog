import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronDown, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { type ReplayObservationApi, VisionObservationsThumbnailRetrieveSize } from '../../generated/api.schemas'
import { scannerLabel } from '../../utils/observation'
import { ReplayScannerTab } from '../replayScannerSceneLogic'
import { type WatchFeedGroupLogicProps, watchFeedGroupLogic } from '../watchFeedGroupLogic'
import { observationKeyMomentMs, watchCardHeadline, watchFeedObservationUrl } from './WatchFeedCard'

/** The card's telemetry properties, so group events join the card they came from. */
type CardContext = Record<string, unknown>

type WatchFeedGroupProps = WatchFeedGroupLogicProps & { similarCount: number; cardContext: CardContext }

function WatchFeedGroupMember({
    observation,
    cardContext,
}: {
    observation: ReplayObservationApi
    cardContext: CardContext
}): JSX.Element {
    const keyMomentMs = observationKeyMomentMs(observation)
    const url = watchFeedObservationUrl(observation)
    const captureOpened = (target: string) => (): void => {
        posthog.capture('replay_vision_watch_group_member_opened', {
            ...cardContext,
            target,
            member_observation_id: observation.id,
        })
    }
    const person = observation.recording_subject_email || observation.distinct_id
    const title = watchCardHeadline(observation)?.title ?? scannerLabel(observation)
    return (
        <li className="flex min-w-0 items-center gap-3" data-attr="vision-watch-feed-group-member">
            <Link
                to={url}
                className="w-24 shrink-0 overflow-hidden rounded border border-primary"
                onClick={captureOpened('thumbnail')}
            >
                <ObservationThumbnail
                    observation={observation}
                    size={VisionObservationsThumbnailRetrieveSize.Small}
                    className="rounded-none border-0"
                />
            </Link>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <Link
                    to={url}
                    className="truncate text-sm font-medium text-default"
                    title={title}
                    onClick={captureOpened('title')}
                >
                    {title}
                </Link>
                <div className="flex min-w-0 items-center gap-1 text-xs text-muted">
                    {person && <span className="truncate">{person}</span>}
                    {person && <span aria-hidden>·</span>}
                    <TZLabel time={observation.created_at} className="shrink-0" />
                </div>
            </div>
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconPlayFilled />}
                to={url}
                tooltip="Watch session"
                onClick={captureOpened('watch')}
            >
                {keyMomentMs !== null ? colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null) : null}
            </LemonButton>
        </li>
    )
}

/** Opens the other sessions in a card's feed group under the card, so a reader can see who else hit it. */
export function WatchFeedGroupToggle({ similarCount, cardContext, ...logicProps }: WatchFeedGroupProps): JSX.Element {
    const { expanded } = useValues(watchFeedGroupLogic(logicProps))
    const { toggleExpanded } = useActions(watchFeedGroupLogic(logicProps))
    return (
        <LemonButton
            size="small"
            type="tertiary"
            sideIcon={
                <IconChevronDown className={expanded ? 'rotate-180 transition-transform' : 'transition-transform'} />
            }
            onClick={() => {
                if (!expanded) {
                    posthog.capture('replay_vision_watch_group_expanded', {
                        ...cardContext,
                        similar_count: similarCount,
                    })
                }
                toggleExpanded()
            }}
            aria-expanded={expanded}
            className="relative z-10 ml-auto"
            data-attr="vision-watch-feed-group-toggle"
        >
            {similarCount === 1 ? '1 similar session' : `${similarCount} similar sessions`}
        </LemonButton>
    )
}

export function WatchFeedGroupList({
    similarCount,
    cardContext,
    ...logicProps
}: WatchFeedGroupProps): JSX.Element | null {
    const { expanded, members, membersLoading } = useValues(watchFeedGroupLogic(logicProps))
    const { loadMembers } = useActions(watchFeedGroupLogic(logicProps))
    if (!expanded) {
        return null
    }
    return (
        // Sits above the card's full-size link, so a click here never opens the card's own session.
        <div className="relative z-10 flex flex-col gap-3 border-t pt-3" data-attr="vision-watch-feed-group">
            {membersLoading ? (
                <div className="flex flex-col gap-3" aria-busy>
                    {Array.from({ length: Math.min(similarCount, 3) }, (_, i) => (
                        <LemonSkeleton key={i} className="h-14 rounded" />
                    ))}
                </div>
            ) : members === null ? (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <span>Couldn't load the similar sessions.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadMembers()}>
                        Try again
                    </LemonButton>
                </div>
            ) : members.shown.length === 0 ? (
                <p className="m-0 text-sm text-secondary">No similar sessions to show right now.</p>
            ) : (
                <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {members.shown.map((member) => (
                        <WatchFeedGroupMember key={member.id} observation={member} cardContext={cardContext} />
                    ))}
                </ul>
            )}
            {/* The list's own total decides, since dismissed or re-ranked sessions can make it differ from the card's count. */}
            {members && members.total > members.shown.length && (
                <Link
                    to={
                        combineUrl(urls.replayVision(logicProps.scannerId), {
                            tab: ReplayScannerTab.Observations,
                            watch_group: logicProps.observationId,
                            date_from: logicProps.dateFrom,
                        }).url
                    }
                    className="self-start text-sm"
                    data-attr="vision-watch-feed-group-see-all"
                    onClick={() =>
                        posthog.capture('replay_vision_watch_group_see_all_clicked', {
                            ...cardContext,
                            similar_count: similarCount,
                        })
                    }
                >
                    See all similar sessions
                </Link>
            )}
        </div>
    )
}
