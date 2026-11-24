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
    Text,
} from '@posthog/quill'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { cohortFilterName, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { cohortsModel } from '~/models/cohortsModel'
import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, CohortType, PropertyFilterType } from '~/types'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { ReleaseLaneSummary } from './ReleaseLaneSummary'
import { UsageTarget } from './releaseLaneUsage'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { Lane, statusLabel } from './releaseTracks'
import { ReleaseRow } from './releaseUtils'

const CONDITIONS_SHOWN = 2

const NO_EDIT_REASON = 'You need edit access to feature flags'

const OPEN_LABEL: Record<Lane['kind'], string> = {
    flag: 'Open flag',
    experiment: 'Open experiment',
    early_access: 'Open feature',
    broadcast: 'Open broadcast',
    survey: 'Open survey',
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
            {groups.slice(0, CONDITIONS_SHOWN).map((group, index) => {
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
            {groups.length > CONDITIONS_SHOWN && (
                <Text size="xs" variant="muted">
                    {`+${groups.length - CONDITIONS_SHOWN} more`}
                </Text>
            )}
        </div>
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
            {target && <ReleaseLaneSummary target={target} from={from} />}
            {lane.kind === 'flag' && <Conditions flag={lane.flag} />}
            <div className="mt-auto">
                <Actions row={row} lane={lane} />
            </div>
        </div>
    )
}
