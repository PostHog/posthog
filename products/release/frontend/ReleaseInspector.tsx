import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconCalendar, IconEllipsis, IconToggle, IconTrash, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Drawer,
    DrawerBody,
    DrawerClose,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Text,
    cn,
} from '@posthog/quill'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { cohortFilterName, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { cohortsModel } from '~/models/cohortsModel'
import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, CohortType, PropertyFilterType } from '~/types'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { KIND_ICON } from './ReleaseLaneCard'
import { ReleaseLaneSummary } from './ReleaseLaneSummary'
import { UsageTarget, usageTarget } from './releaseLaneUsage'
import { ReleaseLaneUsageChart } from './ReleaseLaneUsageChart'
import { releaseLaneUsageLogic } from './releaseLaneUsageLogic'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { Lane, buildTrack, statusLabel } from './releaseTracks'
import { CALENDAR_DAYS_AFTER, ReleaseRow, STAGE_COLOR_VARS } from './releaseUtils'
import { useRolloutStepsByFlag } from './useRolloutStepsByFlag'

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
        <div className="flex flex-col gap-0.5" data-attr="release-inspector-conditions">
            <Text size="xs" variant="muted">
                Release conditions
            </Text>
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

function StatusConfirm({ flag, onDone }: { flag: FeatureFlagApi; onDone: () => void }): JSX.Element {
    const { setFlagActive } = useActions(releaseLogic)
    const turnOn = !flag.active
    return (
        <Item
            variant="outline"
            tone={turnOn ? undefined : 'warning'}
            size="sm"
            data-attr="release-inspector-status-confirm-box"
        >
            <ItemContent>
                <ItemTitle>{turnOn ? 'Turn on this flag now?' : 'Turn off this flag now?'}</ItemTitle>
                <ItemDescription>
                    {turnOn
                        ? 'Users who match its release conditions start to get the feature.'
                        : 'Every user stops getting the feature. Your code gets false for this flag.'}
                </ItemDescription>
                <div className="flex gap-2 pt-1">
                    <Button size="xs" variant="outline" onClick={onDone}>
                        Cancel
                    </Button>
                    <Button
                        size="xs"
                        variant={turnOn ? 'primary' : 'destructive'}
                        onClick={() => {
                            setFlagActive(flag.id, turnOn)
                            onDone()
                        }}
                        data-attr="release-inspector-status-confirm"
                    >
                        {turnOn ? 'Turn on' : 'Turn off'}
                    </Button>
                </div>
            </ItemContent>
        </Item>
    )
}

function Actions({ row, lane, onToggle }: { row: ReleaseRow; lane: Lane; onToggle: () => void }): JSX.Element {
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
                data-attr="release-inspector-open"
            >
                {OPEN_LABEL[lane.kind]}
            </Button>
            {lane.kind === 'flag' && (
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openSchedule(lane.flag.id)}
                    disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                    data-attr="release-inspector-schedule"
                >
                    <IconCalendar />
                    Schedule
                </Button>
            )}
            {(remove || lane.kind === 'flag') && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-sm"
                                className="ml-auto"
                                aria-label={`More actions for ${lane.title}`}
                                data-attr="release-inspector-more"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-48">
                        {lane.kind === 'flag' && (
                            <DropdownMenuItem
                                onClick={onToggle}
                                disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                                data-attr={
                                    lane.flag.active ? 'release-inspector-turn-off' : 'release-inspector-turn-on'
                                }
                            >
                                <IconToggle />
                                {lane.flag.active ? 'Turn off' : 'Turn on'}
                            </DropdownMenuItem>
                        )}
                        {lane.kind === 'flag' && remove && <DropdownMenuSeparator />}
                        {remove && (
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => {
                                    closeCalendarItem()
                                    remove()
                                }}
                                disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                                data-attr="release-inspector-remove"
                            >
                                <IconTrash />
                                Remove from release
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}

const DAYS = 14
const MIN_DAYS = 7
const CHART_HEIGHT = 132

const KIND_LABEL: Record<Lane['kind'], string> = {
    flag: 'Feature flag',
    experiment: 'Experiment',
    early_access: 'Early access feature',
    broadcast: 'Broadcast',
    survey: 'Survey',
}

function inspectorStart(): Dayjs {
    return dayjs()
        .startOf('day')
        .subtract(DAYS - 1, 'day')
}

function inspectorFrom(): string {
    return inspectorStart().format('YYYY-MM-DD')
}

function InspectorChart({ target }: { target: UsageTarget }): JSX.Element {
    const [chart, setChart] = useState<HTMLDivElement | null>(null)
    const { width = 0 } = useResizeObserver<HTMLDivElement>({ ref: chart })
    const from = inspectorStart()
    const { usage, insights } = useValues(releaseLaneUsageLogic({ target, from: from.format('YYYY-MM-DD') }))
    const days = [
        ...(usage?.days ?? []).map((day) => day.day),
        ...(insights?.kind === 'experiment' ? insights.series.map((point) => point.day) : []),
    ].filter((day) => !dayjs(day).isBefore(from, 'day'))
    const first = days.length ? days.reduce((min, day) => (day < min ? day : min)) : null
    const start = first ? dayjs(first).startOf('day') : from
    const span = Math.max(MIN_DAYS, dayjs().startOf('day').diff(start, 'day') + 1)
    const scale = {
        start: dayjs()
            .startOf('day')
            .subtract(span - 1, 'day'),
        days: span,
        day: Math.max(8, Math.floor(width / span)),
    }
    return (
        <div className="flex flex-col gap-1">
            <div ref={setChart} className="overflow-hidden">
                {width > 0 && <ReleaseLaneUsageChart target={target} scale={scale} height={CHART_HEIGHT} bare />}
            </div>
            {!!usage?.days.length && (
                <div className="flex justify-between">
                    <Text size="xxs" variant="muted">
                        {scale.start.format('D MMM')}
                    </Text>
                    <Text size="xxs" variant="muted">
                        Today
                    </Text>
                </div>
            )}
        </div>
    )
}

export function ReleaseInspector({ row }: { row: ReleaseRow }): JSX.Element {
    const { openItem } = useValues(releaseCalendarLogic)
    const { closeCalendarItem } = useActions(releaseCalendarLogic)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const stepsByFlag = useRolloutStepsByFlag(CALENDAR_DAYS_AFTER)
    const [confirming, setConfirming] = useState(false)
    const related = relatedByRelease[row.id]
    const laneKey = openItem?.releaseId === row.id ? openItem.laneKey : null
    const lane = useMemo(
        () => (laneKey ? buildTrack(row, stepsByFlag, related).lanes.find((item) => item.key === laneKey) : undefined),
        [laneKey, row, stepsByFlag, related]
    )
    const [shown, setShown] = useState(lane)

    useEffect(() => setConfirming(false), [laneKey])

    useEffect(() => {
        if (lane) {
            setShown(lane)
        }
    }, [lane])

    const target = shown ? usageTarget(shown, row) : null

    return (
        <Drawer
            open={!!lane}
            onOpenChange={(open) => !open && closeCalendarItem()}
            onOpenChangeComplete={(open) => !open && setShown(undefined)}
            swipeDirection="right"
        >
            <DrawerContent className={cn('[&>div:last-child]:flex-1', STAGE_COLOR_VARS)} data-attr="release-inspector">
                {shown && (
                    <>
                        <DrawerHeader className="border-b">
                            <div className="flex min-w-0 items-start gap-2">
                                <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-4">
                                    {iconForType(KIND_ICON[shown.kind] as never)}
                                </span>
                                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                                    <DrawerTitle className="truncate" title={shown.title}>
                                        {shown.title}
                                    </DrawerTitle>
                                    <div className="flex items-center gap-1.5">
                                        <DrawerDescription>{KIND_LABEL[shown.kind]}</DrawerDescription>
                                        <Badge variant={shown.live ? 'success' : 'default'}>
                                            {statusLabel(shown.status)}
                                        </Badge>
                                    </div>
                                </div>
                                <DrawerClose
                                    render={
                                        <Button
                                            size="icon-xs"
                                            aria-label="Close"
                                            tooltip="Close (Esc)"
                                            data-attr="release-inspector-close"
                                        />
                                    }
                                >
                                    <IconX />
                                </DrawerClose>
                            </div>
                        </DrawerHeader>
                        <DrawerBody viewportClassName="flex flex-col gap-4 py-4">
                            {confirming && shown.kind === 'flag' && (
                                <StatusConfirm flag={shown.flag} onDone={() => setConfirming(false)} />
                            )}
                            {target && <ReleaseLaneSummary target={target} from={inspectorFrom()} />}
                            {target && <InspectorChart target={target} />}
                            {shown.kind === 'flag' && <Conditions flag={shown.flag} />}
                        </DrawerBody>
                        <DrawerFooter className="flex-row border-t">
                            <Actions row={row} lane={shown} onToggle={() => setConfirming(true)} />
                        </DrawerFooter>
                    </>
                )}
            </DrawerContent>
        </Drawer>
    )
}
