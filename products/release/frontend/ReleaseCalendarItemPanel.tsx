import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Badge,
    Button,
    Drawer,
    DrawerBody,
    DrawerContent,
    DrawerDescription,
    DrawerFooter,
    DrawerHeader,
    DrawerTitle,
    Text,
} from '@posthog/quill'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { cohortFilterName, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { cohortsModel } from '~/models/cohortsModel'
import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, CohortType, PropertyFilterType } from '~/types'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseCalendarLogic } from './releaseCalendarLogic'
import { KIND_ICON, laneCardFacts } from './ReleaseLaneCard'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { Lane, buildTrack, sendLabel, statusLabel } from './releaseTracks'
import { CALENDAR_DAYS_AFTER, ReleaseRow } from './releaseUtils'
import { useRolloutStepsByFlag } from './useRolloutStepsByFlag'

const KIND_LABEL: Record<Lane['kind'], string> = {
    flag: 'Feature flag',
    experiment: 'Experiment',
    early_access: 'Early access feature',
    broadcast: 'Broadcast',
    survey: 'Survey',
}

const NO_EDIT_REASON = 'You need edit access to feature flags'

interface ConditionGroup {
    properties?: AnyPropertyFilter[]
    rollout_percentage?: number | null
    variant?: string | null
    description?: string | null
}

function date(value: string): string {
    return dayjs(value).format('D MMM YYYY')
}

function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Text size="xs" weight="medium">
                {title}
            </Text>
            {children}
        </div>
    )
}

function Rows({ rows }: { rows: { key: string; label: string; detail: string }[] }): JSX.Element {
    return (
        <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-2 gap-y-1.5">
            {rows.map((row) => (
                <div key={row.key} className="contents">
                    <Text size="xs" className="truncate tabular-nums" title={row.label}>
                        {row.label}
                    </Text>
                    <Text size="xs" variant="muted" className="truncate" title={row.detail}>
                        {row.detail}
                    </Text>
                </div>
            ))}
        </div>
    )
}

function PropertyLine({
    property,
    cohortsById,
}: {
    property: AnyPropertyFilter
    cohortsById: Partial<Record<string | number, CohortType>>
}): JSX.Element {
    if (property.type === PropertyFilterType.Cohort) {
        return (
            <Text size="xs">
                In cohort{' '}
                <LinkPrimitive
                    to={urls.cohort(property.value)}
                    className="font-medium text-foreground hover:underline"
                    data-attr="release-calendar-item-panel-cohort"
                >
                    {cohortFilterName(property, cohortsById[property.value]?.name)}
                </LinkPrimitive>
            </Text>
        )
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
    return (
        <Text size="xs" className="break-words">
            <span className="font-medium">{label}</span> {operator} {values}
        </Text>
    )
}

function Conditions({ flag }: { flag: FeatureFlagApi }): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    const { loadCohortsByIds } = useActions(cohortsModel)
    const groups = ((flag.filters ?? {}) as { groups?: ConditionGroup[] }).groups ?? []
    const cohortIds = groups
        .flatMap((group) => group.properties ?? [])
        .flatMap((property) =>
            property.type === PropertyFilterType.Cohort && !property.cohort_name ? [Number(property.value)] : []
        )
    const cohortKey = cohortIds.join(',')

    useEffect(() => {
        if (cohortKey) {
            loadCohortsByIds({ ids: cohortKey.split(',').map(Number) })
        }
    }, [cohortKey, loadCohortsByIds])

    if (!groups.length) {
        return null
    }
    return (
        <Section title="Release conditions">
            <div className="flex flex-col gap-2" data-attr="release-calendar-item-panel-conditions">
                {groups.map((group, index) => (
                    <div key={index} className="flex flex-col gap-1 rounded-md border border-border p-2">
                        <div className="flex items-center justify-between gap-2">
                            <Text size="xs" variant="muted">
                                {group.properties?.length ? 'People who match' : 'Everyone'}
                            </Text>
                            <Badge variant="default" className="tabular-nums">
                                {group.rollout_percentage ?? 100}%
                            </Badge>
                        </div>
                        {(group.properties ?? []).map((property, propertyIndex) => (
                            <PropertyLine key={propertyIndex} property={property} cohortsById={cohortsById} />
                        ))}
                        {group.variant && (
                            <Text size="xs" variant="muted">
                                All get the {group.variant} variant
                            </Text>
                        )}
                    </div>
                ))}
            </div>
        </Section>
    )
}

function Variants({ lane }: { lane: Lane | undefined }): JSX.Element | null {
    const variants = lane?.kind === 'flag' ? (lane.audience?.variants ?? []) : []
    if (!variants.length) {
        return null
    }
    return (
        <Section title="Variants">
            <Rows
                rows={variants.map((variant) => ({
                    key: variant.key,
                    label: `${variant.percent}%`,
                    detail: variant.key,
                }))}
            />
        </Section>
    )
}

function History({ lane }: { lane: Lane }): JSX.Element | null {
    const entries =
        lane.kind === 'flag'
            ? [...lane.steps].reverse().map((step) => ({
                  key: `${step.from}-${step.label}`,
                  label: step.label === 'Everyone' ? '100%' : step.label,
                  detail: step.upcoming ? `Planned for ${date(step.from)}` : `From ${date(step.from)}`,
              }))
            : lane.kind === 'broadcast'
              ? [...lane.events].reverse().map((event) => ({
                    key: event.key,
                    label: sendLabel(event),
                    detail: date(event.date),
                }))
              : []
    if (!entries.length) {
        return null
    }
    return (
        <Section title={lane.kind === 'flag' ? 'Rollout history' : 'Sends'}>
            <Rows rows={entries} />
        </Section>
    )
}

function Upcoming({ lane }: { lane: Lane }): JSX.Element | null {
    if (lane.kind !== 'flag' || !lane.events.length) {
        return null
    }
    return (
        <Section title="Scheduled changes">
            <Rows
                rows={lane.events.map((event) => ({
                    key: event.key,
                    label: dayjs(event.date).format('D MMM'),
                    detail: event.detail ? `${event.title}: ${event.detail}` : event.title,
                }))}
            />
        </Section>
    )
}

function LinkedFlag({ row, flagId }: { row: ReleaseRow; flagId: number | undefined }): JSX.Element | null {
    const { openCalendarItem } = useActions(releaseCalendarLogic)
    const flag = row.flags.find((item) => item.id === flagId)
    if (!flag) {
        return null
    }
    return (
        <Section title="Feature flag">
            <div className="flex items-center justify-between gap-2">
                <Text size="xs" className="truncate">
                    {flag.key}
                </Text>
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openCalendarItem(row.id, `flag-${flag.id}`, 'flag')}
                    data-attr="release-calendar-item-panel-show-flag"
                >
                    Show the flag
                </Button>
            </div>
        </Section>
    )
}

function FlagStatusButton({ flag }: { flag: FeatureFlagApi }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { setFlagActive } = useActions(releaseLogic)
    const [confirming, setConfirming] = useState(false)
    const turnOn = !flag.active
    return (
        <>
            <Button
                variant="outline"
                onClick={() => setConfirming(true)}
                disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                data-attr={turnOn ? 'release-calendar-item-panel-turn-on' : 'release-calendar-item-panel-turn-off'}
            >
                {turnOn ? 'Turn on' : 'Turn off'}
            </Button>
            <AlertDialog open={confirming} onOpenChange={setConfirming}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{turnOn ? `Turn on ${flag.key}?` : `Turn off ${flag.key}?`}</AlertDialogTitle>
                        <AlertDialogDescription>
                            {turnOn
                                ? 'The flag starts to apply its release conditions now.'
                                : 'The flag stops for all users now. SDKs get no value for it.'}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setConfirming(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant={turnOn ? 'primary' : 'destructive'}
                            onClick={() => {
                                setFlagActive(flag.id, turnOn)
                                setConfirming(false)
                            }}
                            data-attr="release-calendar-item-panel-status-confirm"
                        >
                            {turnOn ? 'Turn on' : 'Turn off'}
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    )
}

function ItemActions({ row, lane }: { row: ReleaseRow; lane: Lane }): JSX.Element {
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
        <div className="flex w-full flex-wrap items-center gap-2">
            <Button
                variant="primary"
                nativeButton={false}
                render={<LinkPrimitive to={lane.href} />}
                data-attr="release-calendar-item-panel-open"
            >
                Open {KIND_LABEL[lane.kind].toLowerCase()}
            </Button>
            {lane.kind === 'flag' && (
                <>
                    <FlagStatusButton flag={lane.flag} />
                    <Button
                        variant="outline"
                        onClick={() => {
                            closeCalendarItem()
                            openSchedule(lane.flag.id)
                        }}
                        disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                        data-attr="release-calendar-item-panel-schedule"
                    >
                        Schedule a change
                    </Button>
                </>
            )}
            {remove && (
                <Button
                    variant="destructive-outline"
                    onClick={() => {
                        closeCalendarItem()
                        remove()
                    }}
                    disabledReason={canEditReleases ? undefined : NO_EDIT_REASON}
                    data-attr="release-calendar-item-panel-remove"
                >
                    Remove from release
                </Button>
            )}
        </div>
    )
}

function ItemDetails({ row, lane, lanes }: { row: ReleaseRow; lane: Lane; lanes: Lane[] }): JSX.Element {
    const span = 'span' in lane && lane.span && !(lane.kind === 'flag' && lane.steps.length) ? lane.span : undefined
    const facts = laneCardFacts({ lane, span }).filter(([label]) => label !== 'Status')
    const experiment =
        lane.kind === 'experiment' ? row.experiments.find((item) => `experiment-${item.id}` === lane.key) : undefined
    const earlyAccess =
        lane.kind === 'early_access'
            ? row.earlyAccess.find((item) => `early-access-${item.id}` === lane.key)
            : undefined
    const linkedFlagId = experiment
        ? row.flags.find((flag) => flag.key === experiment.feature_flag_key)?.id
        : earlyAccess?.feature_flag?.id
    const linkedLane = lanes.find((item) => item.key === `flag-${linkedFlagId}`)
    const description = experiment?.description || earlyAccess?.description
    return (
        <>
            <DrawerHeader>
                <DrawerTitle className="flex min-w-0 items-center gap-2">
                    <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-4">
                        {iconForType(KIND_ICON[lane.kind] as never)}
                    </span>
                    <span className="truncate">{lane.title}</span>
                </DrawerTitle>
                <DrawerDescription>
                    {KIND_LABEL[lane.kind]} in{' '}
                    <LinkPrimitive to={urls.release(row.id)} className="text-foreground hover:underline">
                        {row.name}
                    </LinkPrimitive>
                </DrawerDescription>
            </DrawerHeader>
            <DrawerBody>
                <div className="flex flex-col gap-5">
                    <div className="flex flex-col gap-3">
                        <div className="flex items-center gap-2">
                            <Text size="xs" variant="muted">
                                Status
                            </Text>
                            <Badge variant={lane.live ? 'success' : 'default'}>{statusLabel(lane.status)}</Badge>
                        </div>
                        {facts.length > 0 && (
                            <Rows rows={facts.map(([label, value]) => ({ key: label, label, detail: value }))} />
                        )}
                    </div>
                    {description && (
                        <Text size="xs" variant="muted" className="whitespace-pre-line">
                            {description}
                        </Text>
                    )}
                    {lane.kind === 'flag' && <Conditions flag={lane.flag} />}
                    <Variants lane={lane.kind === 'flag' ? lane : linkedLane} />
                    <Upcoming lane={lane} />
                    {lane.kind !== 'flag' && <LinkedFlag row={row} flagId={linkedFlagId} />}
                    <History lane={lane} />
                </div>
            </DrawerBody>
            <DrawerFooter>
                <ItemActions row={row} lane={lane} />
            </DrawerFooter>
        </>
    )
}

export function ReleaseCalendarItemPanel(): JSX.Element {
    const { openItem } = useValues(releaseCalendarLogic)
    const { closeCalendarItem } = useActions(releaseCalendarLogic)
    const { rows } = useValues(releaseLogic)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const stepsByFlag = useRolloutStepsByFlag(CALENDAR_DAYS_AFTER)
    const shown = useRef<{ row: ReleaseRow; lane: Lane; lanes: Lane[] } | null>(null)

    useEffect(() => () => closeCalendarItem(), [closeCalendarItem])

    const current = useMemo(() => {
        const row = openItem ? rows.find((item) => item.id === openItem.releaseId) : undefined
        const lanes = row ? buildTrack(row, stepsByFlag, relatedByRelease[row.id]).lanes : []
        const lane = lanes.find((item) => item.key === openItem?.laneKey)
        return row && lane ? { row, lane, lanes } : null
    }, [openItem, rows, stepsByFlag, relatedByRelease])

    if (current) {
        shown.current = current
    }

    return (
        <Drawer open={!!current} onOpenChange={(open: boolean) => !open && closeCalendarItem()} swipeDirection="right">
            <DrawerContent data-attr="release-calendar-item-panel">
                {shown.current && (
                    <ItemDetails row={shown.current.row} lane={shown.current.lane} lanes={shown.current.lanes} />
                )}
            </DrawerContent>
        </Drawer>
    )
}
