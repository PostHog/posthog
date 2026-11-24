import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCalendar, IconEllipsis, IconTrash, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { cohortFilterName, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { cohortsModel } from '~/models/cohortsModel'
import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, CohortType, PropertyFilterType } from '~/types'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { UsageKind, UsageTarget } from './releaseLaneUsage'
import { releaseLaneUsageLogic } from './releaseLaneUsageLogic'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { Lane, statusLabel } from './releaseTracks'
import { ReleaseRow } from './releaseUtils'

const NO_EDIT_REASON = 'You need edit access to feature flags'

const OPEN_LABEL: Record<Lane['kind'], string> = {
    flag: 'Open flag',
    experiment: 'Open experiment',
    early_access: 'Open feature',
    broadcast: 'Open broadcast',
    survey: 'Open survey',
}

const WEEK_LABEL: Record<UsageKind, string> = {
    flag: 'users had this flag checked in the last 7 days',
    experiment: 'users entered the experiment in the last 7 days',
    early_access: 'users opted in or out in the last 7 days',
    survey: 'users answered in the last 7 days',
}

interface ConditionGroup {
    properties?: AnyPropertyFilter[]
    rollout_percentage?: number | null
}

function propertyText(property: AnyPropertyFilter, cohortsById: Partial<Record<string | number, CohortType>>): string {
    if (property.type === PropertyFilterType.Cohort) {
        return cohortFilterName(property, cohortsById[property.value]?.name)
    }
    const label =
        property.type === PropertyFilterType.Flag
            ? property.label || property.key
            : getFilterLabel(
                  property.key,
                  property.type === PropertyFilterType.Person
                      ? TaxonomicFilterGroupType.PersonProperties
                      : TaxonomicFilterGroupType.EventProperties
              ) || property.key
    const operator = isPropertyFilterWithOperator(property) ? allOperatorsToHumanName(property.operator) : 'equals'
    const value = 'value' in property ? property.value : undefined
    const values = value === undefined || value === null ? '' : Array.isArray(value) ? value.join(', ') : String(value)
    return `${label} ${operator} ${values}`.trim()
}

function Conditions({ flag }: { flag: FeatureFlagApi }): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    const { loadCohortsByIds } = useActions(cohortsModel)
    const groups = ((flag.filters ?? {}) as { groups?: ConditionGroup[] }).groups ?? []
    const cohortKey = groups
        .flatMap((group) => group.properties ?? [])
        .flatMap((property) =>
            property.type === PropertyFilterType.Cohort && !property.cohort_name ? [Number(property.value)] : []
        )
        .join(',')

    useEffect(() => {
        if (cohortKey) {
            loadCohortsByIds({ ids: cohortKey.split(',').map(Number) })
        }
    }, [cohortKey, loadCohortsByIds])

    if (!groups.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-0.5" data-attr="release-lane-detail-conditions">
            {groups.map((group, index) => {
                const text = group.properties?.length
                    ? group.properties.map((property) => propertyText(property, cohortsById)).join(' and ')
                    : 'Everyone'
                return (
                    <div key={index} className="flex min-w-0 items-baseline gap-2">
                        <Text size="xs" className="min-w-0 flex-1 truncate" title={text}>
                            {text}
                        </Text>
                        <Text size="xs" variant="muted" className="shrink-0 tabular-nums">
                            {group.rollout_percentage ?? 100}%
                        </Text>
                    </div>
                )
            })}
        </div>
    )
}

function Usage({ target, from }: { target: UsageTarget; from: string }): JSX.Element {
    const { usage, usageLoading } = useValues(releaseLaneUsageLogic({ target, from }))
    if (usageLoading && !usage) {
        return <Skeleton className="h-10 w-full" />
    }
    if (!usage) {
        return (
            <Text size="xs" variant="muted">
                Usage could not load.
            </Text>
        )
    }
    const total = usage.split.reduce((sum, item) => sum + item.users, 0)
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-baseline gap-1.5">
                <Text size="lg" weight="semibold" className="tabular-nums">
                    {humanFriendlyNumber(usage.weekUsers)}
                </Text>
                <Text size="xs" variant="muted">
                    {WEEK_LABEL[target.kind]}
                </Text>
            </div>
            {usage.split.length > 0 && total > 0 && (
                <div className="flex flex-wrap gap-x-3 gap-y-0.5" data-attr="release-lane-detail-split">
                    {usage.split.map((item) => (
                        <Text key={item.label} size="xs" variant="muted" className="tabular-nums">
                            <span className="text-foreground">{item.label}</span>{' '}
                            {target.kind === 'survey'
                                ? humanFriendlyNumber(item.users)
                                : `${Math.round((item.users / total) * 100)}%`}
                        </Text>
                    ))}
                </div>
            )}
        </div>
    )
}

function LastChange({ flagId }: { flagId: number }): JSX.Element | null {
    const { flagActivity } = useValues(releaseCalendarLogic)
    const entry = flagActivity[flagId]?.[0]
    if (!entry) {
        return null
    }
    const who = entry.user?.first_name || entry.user?.email || (entry.is_system ? 'PostHog' : 'someone')
    return (
        <Text size="xs" variant="muted" className="truncate">
            <span>Changed </span>
            <TZLabel time={entry.created_at} />
            <span>{` by ${who}`}</span>
        </Text>
    )
}

function StatusToggle({ lane }: { lane: Lane }): JSX.Element | null {
    const { canEditReleases } = useValues(releaseLogic)
    const { setFlagActive } = useActions(releaseLogic)
    const [confirming, setConfirming] = useState(false)
    const flag = lane.kind === 'flag' ? lane.flag : null
    const turnOn = !flag?.active

    useEffect(() => setConfirming(false), [lane.key])

    if (!flag) {
        return null
    }
    if (!confirming) {
        return (
            <Button
                variant="outline"
                size="xs"
                onClick={() => setConfirming(true)}
                disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                data-attr={turnOn ? 'release-lane-detail-turn-on' : 'release-lane-detail-turn-off'}
            >
                {turnOn ? 'Turn on' : 'Turn off'}
            </Button>
        )
    }
    return (
        <Item variant="outline" tone={turnOn ? undefined : 'warning'} size="sm" className="basis-full">
            <ItemContent>
                <ItemTitle>{turnOn ? 'Turn on this flag now?' : 'Turn off this flag now?'}</ItemTitle>
                <ItemDescription>
                    {turnOn
                        ? 'Users who match its release conditions start to get the feature.'
                        : 'Every user stops getting the feature. Your code gets false for this flag.'}
                </ItemDescription>
                <div className="flex gap-2 pt-1">
                    <Button size="xs" variant="outline" onClick={() => setConfirming(false)}>
                        Cancel
                    </Button>
                    <Button
                        size="xs"
                        variant={turnOn ? 'primary' : 'destructive'}
                        onClick={() => {
                            setFlagActive(flag.id, turnOn)
                            setConfirming(false)
                        }}
                        data-attr="release-lane-detail-status-confirm"
                    >
                        {turnOn ? 'Turn on' : 'Turn off'}
                    </Button>
                </div>
            </ItemContent>
        </Item>
    )
}

function Actions({ row, lane }: { row: ReleaseRow; lane: Lane }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { openSchedule, unlinkFlag, unlinkBroadcast } = useActions(releaseLogic)
    const { unlinkRelated } = useActions(releaseRelatedLogic)
    const { closeCalendarItem } = useActions(releaseCalendarLogic)
    const remove =
        lane.kind === 'flag'
            ? () => unlinkFlag(row.id, lane.flag.id)
            : lane.kind === 'survey'
              ? () => unlinkRelated(row.id, 'survey', lane.survey.id)
              : lane.kind === 'broadcast'
                ? () => unlinkBroadcast(row.id, lane.key.replace(/^broadcast-/, ''))
                : null
    return (
        <div className="flex items-center gap-1.5">
            <Button
                size="sm"
                variant="primary"
                nativeButton={false}
                render={<LinkPrimitive to={lane.href} />}
                data-attr="release-lane-detail-open"
            >
                {OPEN_LABEL[lane.kind]}
            </Button>
            {lane.kind === 'flag' && (
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openSchedule(lane.flag.id)}
                    disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                    data-attr="release-lane-detail-schedule"
                >
                    <IconCalendar />
                    Schedule
                </Button>
            )}
            {remove && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-sm"
                                className="ml-auto"
                                aria-label={`More actions for ${lane.title}`}
                                data-attr="release-lane-detail-more"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-48">
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => {
                                closeCalendarItem()
                                remove()
                            }}
                            disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                            data-attr="release-lane-detail-remove"
                        >
                            <IconTrash />
                            Remove from release
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}

function LinkedFlag({ row, flagId }: { row: ReleaseRow; flagId: number | undefined }): JSX.Element | null {
    const { openCalendarItem } = useActions(releaseCalendarLogic)
    const flag = row.flags.find((item) => item.id === flagId)
    if (!flag) {
        return null
    }
    return (
        <Text size="xs" variant="muted" className="truncate">
            <span>Flag </span>
            <button
                type="button"
                className="cursor-pointer font-medium text-foreground hover:underline"
                onClick={() => openCalendarItem(row.id, `flag-${flag.id}`, 'flag')}
                data-attr="release-lane-detail-show-flag"
            >
                {flag.key}
            </button>
        </Text>
    )
}

function SurveyQuestion(): JSX.Element | null {
    const { panelSurvey } = useValues(releaseCalendarLogic)
    const questions = (panelSurvey?.questions ?? []) as { question?: string }[]
    if (!questions.length) {
        return null
    }
    const more = questions.length - 1
    return (
        <Text
            size="xs"
            variant="muted"
            className="line-clamp-2"
            title={questions.map((item) => item.question).join('\n')}
        >
            <span>Asks </span>
            <span className="text-foreground">{questions[0].question}</span>
            {more > 0 && <span>{` (${more} more ${more === 1 ? 'question' : 'questions'})`}</span>}
        </Text>
    )
}

export function ReleaseLaneDetail({
    row,
    lane,
    target,
    from,
}: {
    row: ReleaseRow
    lane: Lane
    target: UsageTarget | null
    from: string
}): JSX.Element {
    const { closeCalendarItem } = useActions(releaseCalendarLogic)
    const experiment =
        lane.kind === 'experiment' ? row.experiments.find((item) => `experiment-${item.id}` === lane.key) : undefined
    const earlyAccess =
        lane.kind === 'early_access'
            ? row.earlyAccess.find((item) => `early-access-${item.id}` === lane.key)
            : undefined
    const linkedFlagId = experiment
        ? row.flags.find((flag) => flag.key === experiment.feature_flag_key)?.id
        : lane.kind === 'survey'
          ? (lane.survey.linkedFlagId ?? undefined)
          : earlyAccess?.feature_flag?.id

    return (
        <div className="flex h-full min-w-0 flex-col gap-2 overflow-y-auto py-2" data-attr="release-lane-detail">
            <div className="flex flex-wrap items-center gap-2">
                <Badge variant={lane.live ? 'success' : 'default'}>{statusLabel(lane.status)}</Badge>
                <StatusToggle lane={lane} />
                <Button
                    size="icon-xs"
                    className="ml-auto"
                    aria-label="Close details"
                    onClick={closeCalendarItem}
                    data-attr="release-lane-detail-close"
                >
                    <IconX />
                </Button>
            </div>
            {target && <Usage target={target} from={from} />}
            <div className="flex flex-col gap-0.5">
                {lane.kind === 'flag' && <LastChange flagId={lane.flag.id} />}
                {lane.kind === 'survey' && <SurveyQuestion />}
                {lane.kind !== 'flag' && <LinkedFlag row={row} flagId={linkedFlagId} />}
            </div>
            {lane.kind === 'flag' && <Conditions flag={lane.flag} />}
            <div className="mt-auto">
                <Actions row={row} lane={lane} />
            </div>
        </div>
    )
}
