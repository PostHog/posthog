import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconChevronDown, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ObservationThumbnail } from '../../components/ObservationThumbnail'
import { type ReplayObservationApi, VisionObservationsThumbnailRetrieveSize } from '../../generated/api.schemas'
import { scannerLabel } from '../../utils/observation'
import { type HighlightFeedGroupLogicProps, highlightFeedGroupLogic } from '../highlightFeedGroupLogic'
import { ReplayScannerTab } from '../replayScannerSceneLogic'
import { observationKeyMomentMs, highlightCardHeadline, highlightFeedObservationUrl } from './HighlightFeedCard'

/** The card's telemetry properties, so group events join the card they came from. */
type CardContext = Record<string, unknown>

type HighlightFeedGroupProps = HighlightFeedGroupLogicProps & {
    similarCount: number
    /** Distinct people across the whole group, the card's own session included. */
    affectedPeople: number | null
    cardContext: CardContext
}

/** Shared by the card's reason line and its button, so the two always show the same count. */
export function similarSessionsLabel(similarCount: number): string {
    return pluralize(similarCount, 'similar session')
}

function groupSummary(similarCount: number, affectedPeople: number | null): string {
    const others = `This session and ${pluralize(similarCount, 'similar one')}`
    return affectedPeople ? `${others}, from ${pluralize(affectedPeople, 'person', 'people')}` : others
}

function HighlightFeedGroupMember({
    observation,
    cardContext,
}: {
    observation: ReplayObservationApi
    cardContext: CardContext
}): JSX.Element {
    const keyMomentMs = observationKeyMomentMs(observation)
    const url = highlightFeedObservationUrl(observation)
    const captureOpened = (target: string) => (): void => {
        posthog.capture('replay_vision_watch_group_member_opened', {
            ...cardContext,
            target,
            member_observation_id: observation.id,
        })
    }
    const person = observation.recording_subject_email || observation.distinct_id
    const title = highlightCardHeadline(observation)?.title ?? scannerLabel(observation)
    return (
        <li className="flex min-w-0 items-center gap-3" data-attr="vision-highlight-feed-group-member">
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
                    className="line-clamp-2 text-sm font-medium wrap-anywhere text-default"
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
                className="shrink-0"
            >
                {keyMomentMs !== null ? colonDelimitedDuration(Math.floor(keyMomentMs / 1000), null) : null}
            </LemonButton>
        </li>
    )
}

function HighlightFeedGroupList({
    similarCount,
    affectedPeople,
    cardContext,
    ...logicProps
}: HighlightFeedGroupProps): JSX.Element {
    const { members, membersLoading } = useValues(highlightFeedGroupLogic(logicProps))
    const { loadMembers } = useActions(highlightFeedGroupLogic(logicProps))
    return (
        <div className="flex w-[30rem] max-w-[90vw] flex-col gap-3 p-2" data-attr="vision-highlight-feed-group">
            <p className="m-0 text-xs text-secondary">{groupSummary(similarCount, affectedPeople)}</p>
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
                        <HighlightFeedGroupMember key={member.id} observation={member} cardContext={cardContext} />
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
                            watch_category: logicProps.categories,
                        }).url
                    }
                    className="self-start text-sm"
                    data-attr="vision-highlight-feed-group-see-all"
                    onClick={() =>
                        posthog.capture('replay_vision_watch_group_see_all_clicked', {
                            ...cardContext,
                            similar_count: similarCount,
                        })
                    }
                >
                    See all {members.total} similar sessions
                </Link>
            )}
        </div>
    )
}

/**
 * Opens the other sessions in a card's duplicate group in a popover, so a reader can see who else hit it
 * without the card growing and pushing its row out of line with the rest of the grid.
 */
export function HighlightFeedGroupToggle(props: HighlightFeedGroupProps): JSX.Element {
    const { similarCount, affectedPeople, cardContext, ...logicProps } = props
    // Mounted with the card, so members loaded once survive closing and reopening the popover.
    const { members, membersLoading } = useValues(highlightFeedGroupLogic(logicProps))
    const { loadMembers } = useActions(highlightFeedGroupLogic(logicProps))
    const [open, setOpen] = useState(false)
    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={(visible) => {
                if (visible) {
                    posthog.capture('replay_vision_watch_group_expanded', {
                        ...cardContext,
                        similar_count: similarCount,
                    })
                    if (members === null && !membersLoading) {
                        loadMembers()
                    }
                }
                setOpen(visible)
            }}
            // A click on "Try again" must leave the list open to show the retried result.
            closeOnClickInside={false}
            placement="bottom-end"
            overlay={<HighlightFeedGroupList {...props} />}
        >
            <LemonButton
                size="small"
                type="tertiary"
                sideIcon={
                    <IconChevronDown className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
                }
                aria-expanded={open}
                className="relative z-10 ml-auto"
                data-attr="vision-highlight-feed-group-toggle"
            >
                {similarSessionsLabel(similarCount)}
            </LemonButton>
        </LemonDropdown>
    )
}
