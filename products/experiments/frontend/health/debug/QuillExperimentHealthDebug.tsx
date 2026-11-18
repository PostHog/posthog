import { useActions, useValues } from 'kea'
import { type ReactNode } from 'react'

import { IconRefresh, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Skeleton,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { QuillSectionHeading } from 'scenes/experiments/ExperimentView/QuillCardParts'

import { QuillSetupFactsTable } from '../../setupInspector/QuillSetupFactsTable'
import { SdkProfileSection } from '../../setupInspector/sections/SdkProfileSection'
import { TeamDefaultsSection } from '../../setupInspector/sections/TeamDefaultsSection'
import { formatCount, formatTimestamp, formatYesNo } from '../../setupInspector/setupInspectorUtils'
import { experimentHealthDebugLogic } from './experimentHealthDebugLogic'
import {
    CHECK_RESULTS_DESCRIPTION,
    CHECK_RESULTS_TITLE,
    DRIFT_TOOLTIP,
    EXPOSURES_INPUT_NOTE,
    FLAG_CHANGES_DESCRIPTION,
    FLAG_CHANGES_TITLE,
    FLAG_CONFIGURATION_DESCRIPTION,
    FLAG_CONFIGURATION_TITLE,
    FLAG_TRAFFIC_DESCRIPTION,
    FLAG_TRAFFIC_TITLE,
    HEALTH_DEBUG_DESCRIPTION,
    HEALTH_DEBUG_DOMAINS,
    HEALTH_DEBUG_TITLE,
    INPUTS_DESCRIPTION,
    INPUTS_TITLE,
    NO_RELEASE_CONDITIONS,
    PROJECT_FACTS_DESCRIPTION,
    PROJECT_FACTS_NOT_LOADED,
    SDK_PROFILE_SKIPPED,
} from './healthDebugCopy'
import type { HealthDebugFlagChange, HealthDebugReleaseCondition } from './healthDebugInputs'
import { HEALTH_DEBUG_DOMAIN_LABELS, type HealthDebugCheck, type HealthDebugDomain } from './healthDebugReport'

const SEVERITY_BADGE: Record<NonNullable<HealthDebugCheck['severity']>, 'destructive' | 'warning' | 'default'> = {
    critical: 'destructive',
    warning: 'warning',
    info: 'default',
}

function Section({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <QuillSectionHeading>{title}</QuillSectionHeading>
            {description && (
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    {description}
                </Text>
            )}
            {children}
        </section>
    )
}

function Muted({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Text size="sm" variant="muted" render={<p className="m-0" />}>
            {children}
        </Text>
    )
}

function TableCard<T>({
    columns,
    data,
    getRowId,
    empty,
}: {
    columns: DataTableProps<T, unknown>['columns']
    data: T[]
    getRowId: (row: T, index: number) => string
    empty?: ReactNode
}): JSX.Element {
    return (
        <Card size="sm" flush className="pt-0">
            <DataTable columns={columns} data={data} fullWidth size="sm" getRowId={getRowId} empty={empty} />
        </Card>
    )
}

function ComputedAt({ timestamp }: { timestamp: string }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span translate="no" />}>
            computed {formatTimestamp(timestamp)}
        </Text>
    )
}

function CheckResults(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const { healthDebugChecks } = useValues(experimentHealthDebugLogic({ experimentId }))
    const { setActiveDomain } = useActions(experimentHealthDebugLogic({ experimentId }))

    const columns: DataTableProps<HealthDebugCheck, unknown>['columns'] = [
        {
            id: 'check',
            header: 'Check',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <div className="flex flex-col">
                    <code translate="no">{original.check}</code>
                    <Text size="xs" variant="muted">
                        from the {original.source}
                    </Text>
                </div>
            ),
        },
        {
            id: 'result',
            header: 'Result',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <div className="flex min-w-64 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-1">
                        {original.severity && (
                            <Badge variant={SEVERITY_BADGE[original.severity]}>{original.severity}</Badge>
                        )}
                        <code translate="no">{original.result}</code>
                        {original.computedAt && <ComputedAt timestamp={original.computedAt} />}
                    </span>
                    {original.browser !== null && (
                        <Text size="xs" variant="muted" render={<span className="flex flex-wrap items-center gap-1" />}>
                            <span>{original.browserLabel}:</span>
                            <code translate="no">{original.browser}</code>
                            {original.browserComputedAt && <ComputedAt timestamp={original.browserComputedAt} />}
                            {original.difference === 'disagrees' && <Badge variant="destructive">Differs</Badge>}
                            {original.difference === 'drift' && (
                                <Tooltip>
                                    <TooltipTrigger render={<Badge tabIndex={0} />}>Drift</TooltipTrigger>
                                    <TooltipContent className="max-w-80">{DRIFT_TOOLTIP}</TooltipContent>
                                </Tooltip>
                            )}
                        </Text>
                    )}
                </div>
            ),
        },
        {
            id: 'reads',
            header: 'Reads',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <div className="flex min-w-44 flex-wrap gap-1">
                    {original.reads.map((domain) => (
                        <Button
                            key={domain}
                            variant="outline"
                            size="xs"
                            onClick={() => setActiveDomain(domain)}
                            data-attr="experiment-health-debug-reads"
                        >
                            {HEALTH_DEBUG_DOMAIN_LABELS[domain]}
                        </Button>
                    ))}
                </div>
            ),
        },
        {
            id: 'note',
            header: 'Details',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) => (
                <Text size="xs" render={<span className="block min-w-48" />}>
                    {original.note}
                </Text>
            ),
        },
    ]

    return <TableCard columns={columns} data={healthDebugChecks} getRowId={(check) => check.check} />
}

function FlagInputs(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const {
        flagFacts,
        releaseConditions,
        flagHistoryFacts,
        flagChanges,
        trafficFacts,
        healthInputs,
        healthInputsLoading,
        healthInputsError,
    } = useValues(experimentHealthDebugLogic({ experimentId }))
    const trafficRead = !!healthInputs?.condition_set_traffic
    const flagHistoryChecked = !!healthInputs?.flag_history?.checked

    const conditionColumns: DataTableProps<HealthDebugReleaseCondition, unknown>['columns'] = [
        { id: 'number', header: 'Set', accessorFn: (condition) => condition.number },
        {
            id: 'rollout',
            header: 'Rollout',
            meta: { align: 'right' },
            accessorFn: (condition) => condition.rolloutPercentage ?? -1,
            cell: ({ row: { original } }) =>
                original.rolloutPercentage === null ? 'Unset' : `${original.rolloutPercentage}%`,
        },
        {
            id: 'properties',
            header: 'Properties',
            meta: { align: 'right' },
            accessorFn: (condition) => condition.propertyCount ?? -1,
            cell: ({ row: { original } }) => original.propertyCount ?? 'Unknown',
        },
        {
            id: 'reachable',
            header: 'Reachable',
            enableSorting: false,
            cell: ({ row: { original } }) => formatYesNo(original.reachable),
        },
        {
            id: 'pinned',
            header: 'Pinned variant',
            enableSorting: false,
            cell: ({ row: { original } }) =>
                original.pinnedVariant ? (
                    <code translate="no">{original.pinnedVariant}</code>
                ) : (
                    <Text variant="muted">None</Text>
                ),
        },
        ...(trafficRead
            ? [
                  {
                      id: 'people',
                      header: 'People in the window',
                      meta: { align: 'right' as const },
                      enableSorting: false,
                      cell: ({ row: { original } }: { row: { original: HealthDebugReleaseCondition } }) =>
                          formatCount(original.people),
                  },
              ]
            : []),
    ]

    const changeColumns: DataTableProps<HealthDebugFlagChange, unknown>['columns'] = [
        { id: 'changedAt', header: 'Changed at', accessorFn: (change) => change.changedAt },
        { id: 'changed', header: 'Changed', accessorFn: (change) => change.changed },
        { id: 'before', header: 'Before', enableSorting: false, accessorFn: (change) => change.before },
        { id: 'after', header: 'After', enableSorting: false, accessorFn: (change) => change.after },
        ...(flagHistoryChecked
            ? [
                  {
                      id: 'counted',
                      header: 'Counts',
                      enableSorting: false,
                      cell: ({ row: { original } }: { row: { original: HealthDebugFlagChange } }) =>
                          formatYesNo(original.counted),
                  },
              ]
            : []),
    ]

    return (
        <div className="flex flex-col gap-4">
            {healthInputsError && (
                <Item variant="outline" size="sm" tone="destructive">
                    <ItemMedia variant="icon" aria-hidden>
                        <IconWarning />
                    </ItemMedia>
                    <ItemContent className="min-w-0">
                        <ItemDescription className="line-clamp-none">{healthInputsError}</ItemDescription>
                    </ItemContent>
                </Item>
            )}
            <Section title={FLAG_CONFIGURATION_TITLE} description={FLAG_CONFIGURATION_DESCRIPTION}>
                <QuillSetupFactsTable facts={flagFacts} />
                <TableCard
                    columns={conditionColumns}
                    data={releaseConditions}
                    getRowId={(condition) => String(condition.number)}
                    empty={
                        healthInputsLoading ? (
                            <Skeleton className="h-6 w-full" />
                        ) : (
                            <Text size="xs" variant="muted">
                                {NO_RELEASE_CONDITIONS}
                            </Text>
                        )
                    }
                />
            </Section>
            <Section title={FLAG_CHANGES_TITLE} description={FLAG_CHANGES_DESCRIPTION}>
                <QuillSetupFactsTable facts={flagHistoryFacts} />
                {flagChanges.length > 0 && (
                    <TableCard
                        columns={changeColumns}
                        data={flagChanges}
                        getRowId={(change, index) => `${change.changedAt}-${index}`}
                    />
                )}
            </Section>
            <Section title={FLAG_TRAFFIC_TITLE} description={FLAG_TRAFFIC_DESCRIPTION}>
                <QuillSetupFactsTable facts={trafficFacts} />
            </Section>
        </div>
    )
}

function ProjectInputs(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const { healthInputs, healthInputsLoading } = useValues(experimentHealthDebugLogic({ experimentId }))

    if (!healthInputs) {
        return healthInputsLoading ? (
            <div className="flex flex-col gap-2">
                {Array.from({ length: 6 }, (_, index) => (
                    <Skeleton key={index} className="h-6 w-full" />
                ))}
            </div>
        ) : (
            <Muted>{PROJECT_FACTS_NOT_LOADED}</Muted>
        )
    }
    return (
        <div className="flex flex-col gap-4">
            <Muted>{PROJECT_FACTS_DESCRIPTION}</Muted>
            <SdkProfileSection section={healthInputs.project.sdk_profile} skippedMessage={SDK_PROFILE_SKIPPED} />
            <TeamDefaultsSection section={healthInputs.project.team_defaults} />
        </div>
    )
}

export function QuillExperimentHealthDebug(): JSX.Element {
    const { experimentId } = useValues(experimentLogic)
    const logic = experimentHealthDebugLogic({ experimentId })
    const {
        activeDomain,
        healthDebugSummary,
        experimentFacts,
        metricFacts,
        exposureFacts,
        healthDebugRawData,
        healthInputsLoading,
    } = useValues(logic)
    const { setActiveDomain, loadHealthInputs } = useActions(logic)

    const domainContent: Record<HealthDebugDomain, JSX.Element> = {
        experiment: <QuillSetupFactsTable facts={experimentFacts} />,
        flag: <FlagInputs />,
        exposures: (
            <div className="flex flex-col gap-2">
                <Muted>{EXPOSURES_INPUT_NOTE}</Muted>
                <QuillSetupFactsTable facts={exposureFacts} />
            </div>
        ),
        metrics: <QuillSetupFactsTable facts={metricFacts} />,
        project: <ProjectInputs />,
        raw: (
            <CodeSnippet language={Language.JSON} thing="health debug data" maxLinesWithoutExpansion={20}>
                {JSON.stringify(healthDebugRawData, null, 2)}
            </CodeSnippet>
        ),
    }

    return (
        <div className="flex flex-col gap-6" data-attr="experiment-health-debug">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                        <Heading size="base" render={<h3 className="m-0" />}>
                            {HEALTH_DEBUG_TITLE}
                        </Heading>
                        <Badge>Staff only</Badge>
                    </span>
                    <Muted>{HEALTH_DEBUG_DESCRIPTION}</Muted>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    loading={healthInputsLoading}
                    onClick={() => loadHealthInputs()}
                    data-attr="experiment-health-debug-reload"
                >
                    <IconRefresh />
                    Reload inputs
                </Button>
            </div>
            <QuillSetupFactsTable facts={healthDebugSummary} />
            <Section title={CHECK_RESULTS_TITLE} description={CHECK_RESULTS_DESCRIPTION}>
                <CheckResults />
            </Section>
            <Section title={INPUTS_TITLE} description={INPUTS_DESCRIPTION}>
                <ToggleGroup
                    variant="outline"
                    size="sm"
                    value={[activeDomain]}
                    onValueChange={(next: string[]) => next[0] && setActiveDomain(next[0] as HealthDebugDomain)}
                    aria-label="Input domain"
                >
                    {HEALTH_DEBUG_DOMAINS.map((domain) => (
                        <ToggleGroupItem key={domain} value={domain}>
                            {HEALTH_DEBUG_DOMAIN_LABELS[domain]}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                {domainContent[activeDomain]}
            </Section>
        </div>
    )
}
