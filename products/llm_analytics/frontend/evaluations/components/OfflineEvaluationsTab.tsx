import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconArrowLeft, IconExternal, IconInfo, IconRefresh, IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { truncateValue } from '../../utils'
import {
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineMetricColumn,
    OfflineMetricValue,
    offlineEvaluationsLogic,
} from '../offlineEvaluationsLogic'

const TEXT_PREVIEW_MAX_WIDTH_CLASS = 'max-w-80'

function formatMetricScore(score: number): string {
    return score.toLocaleString(undefined, { maximumFractionDigits: 3 })
}

function formatMetricPercentage(score: number): string {
    return `${score.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
}

function getNormalizedPercentage(value: OfflineMetricValue): number | null {
    if (value.score === null) {
        return null
    }

    if (value.scoreMin !== null && value.scoreMax !== null && value.scoreMax > value.scoreMin) {
        return ((value.score - value.scoreMin) / (value.scoreMax - value.scoreMin)) * 100
    }

    if (value.score >= 0 && value.score <= 1) {
        return value.score * 100
    }

    return null
}

function getStatusLabel(status: string): string {
    switch (status) {
        case 'not_applicable':
            return 'N/A'
        case 'skipped':
            return 'Skipped'
        case 'error':
            return 'Error'
        case 'ok':
            return 'OK'
        default:
            return status
    }
}

function getStatusType(status: string): 'success' | 'warning' | 'danger' | 'muted' {
    switch (status) {
        case 'ok':
            return 'success'
        case 'not_applicable':
            return 'warning'
        case 'error':
            return 'danger'
        default:
            return 'muted'
    }
}

function MetricIndicators({ value }: { value: OfflineMetricValue }): JSX.Element | null {
    const hasReasoning = Boolean(value.reasoning)
    const reasoningIndicator = hasReasoning ? (
        <Tooltip title={<div className="max-w-md whitespace-pre-wrap break-words text-xs">{value.reasoning}</div>}>
            <span className="text-muted">
                <IconInfo className="size-3" />
            </span>
        </Tooltip>
    ) : null

    const traceIndicator = value.traceId ? (
        <Tooltip title={<div className="font-mono text-xs">{value.traceId}</div>}>
            <Link to={urls.llmAnalyticsTrace(value.traceId)} className="text-muted">
                <IconExternal className="size-3" />
            </Link>
        </Tooltip>
    ) : null

    if (!traceIndicator && !reasoningIndicator) {
        return null
    }

    return (
        <>
            {traceIndicator}
            {reasoningIndicator}
        </>
    )
}

function MetricCellWrapper({
    value,
    metricDetails,
    children,
}: {
    value: OfflineMetricValue
    metricDetails: JSX.Element
    children: JSX.Element
}): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <Tooltip title={metricDetails}>{children}</Tooltip>
            <MetricIndicators value={value} />
        </div>
    )
}

function EntityNameCell({ name, id }: { name: string | null; id: string }): JSX.Element {
    if (!name) {
        return <span className="font-mono text-xs">{id}</span>
    }

    return (
        <Tooltip title={<div className="max-w-md whitespace-pre-wrap break-words text-xs">{name}</div>}>
            <div className="flex flex-col leading-tight">
                <span>{name}</span>
                <span className="font-mono text-xs text-muted">{id}</span>
            </div>
        </Tooltip>
    )
}

function compareLastSeenDesc(left: string | null, right: string | null): number {
    const leftValue = left ? Date.parse(left) : 0
    const rightValue = right ? Date.parse(right) : 0
    return rightValue - leftValue
}

function LastSeenCell({ value }: { value: string | null }): JSX.Element {
    return value ? <TZLabel time={value} /> : <span className="text-muted">-</span>
}

function MetricCell({ value }: { value?: OfflineMetricValue }): JSX.Element {
    if (!value) {
        return <span className="text-muted">-</span>
    }

    const status = value.status || 'unknown'
    const normalizedPercentage = getNormalizedPercentage(value)
    const metricDetails = (
        <div className="max-w-md space-y-1 text-xs">
            <div>Status: {getStatusLabel(status)}</div>
            {value.resultType ? <div>Type: {value.resultType}</div> : null}
            {value.score !== null ? <div>Raw score: {formatMetricScore(value.score)}</div> : null}
            {normalizedPercentage !== null ? (
                <div>Normalized score: {formatMetricPercentage(normalizedPercentage)}</div>
            ) : null}
            {value.scoreMin !== null && value.scoreMax !== null ? (
                <div>
                    Range: {value.scoreMin} to {value.scoreMax}
                </div>
            ) : null}
            {value.reasoning ? (
                <div>
                    <div className="font-semibold">Reasoning</div>
                    <div className="whitespace-pre-wrap break-words">{value.reasoning}</div>
                </div>
            ) : null}
        </div>
    )

    if (status !== 'ok') {
        return (
            <MetricCellWrapper
                value={value}
                metricDetails={metricDetails}
                children={
                    <span>
                        <LemonTag type={getStatusType(status)}>{getStatusLabel(status)}</LemonTag>
                    </span>
                }
            />
        )
    }

    if (value.resultType === 'binary') {
        const booleanValue = value.score === 1 ? true : value.score === 0 ? false : null
        const booleanLabel = booleanValue === null ? 'Unknown' : booleanValue ? 'True' : 'False'
        const booleanTagType = booleanValue === null ? 'muted' : booleanValue ? 'success' : 'danger'

        return (
            <MetricCellWrapper
                value={value}
                metricDetails={metricDetails}
                children={
                    <span>
                        <LemonTag type={booleanTagType}>{booleanLabel}</LemonTag>
                    </span>
                }
            />
        )
    }

    if (value.score === null) {
        return (
            <MetricCellWrapper
                value={value}
                metricDetails={metricDetails}
                children={
                    <span>
                        <LemonTag type="muted">No score</LemonTag>
                    </span>
                }
            />
        )
    }

    return (
        <MetricCellWrapper
            value={value}
            metricDetails={metricDetails}
            children={
                <div className="flex flex-col leading-tight">
                    <span className="font-medium">
                        {normalizedPercentage !== null ? formatMetricPercentage(normalizedPercentage) : '-'}
                    </span>
                    <span className="text-muted text-xs">{formatMetricScore(value.score)}</span>
                </div>
            }
        />
    )
}

function PreviewCell({ value }: { value: string | null }): JSX.Element {
    if (!value) {
        return <span className="text-muted">-</span>
    }

    return (
        <Tooltip title={<div className="max-w-2xl whitespace-pre-wrap break-words text-xs">{value}</div>}>
            <div className={`${TEXT_PREVIEW_MAX_WIDTH_CLASS} text-xs leading-5 line-clamp-2 break-words`}>{value}</div>
        </Tooltip>
    )
}

function SourceCell({ item }: { item: OfflineExperimentItem }): JSX.Element {
    if (item.datasetId) {
        return (
            <div className="flex flex-col">
                <Link
                    to={
                        item.datasetItemId
                            ? urls.llmAnalyticsDataset(item.datasetId, { item: item.datasetItemId })
                            : urls.llmAnalyticsDataset(item.datasetId)
                    }
                    className="font-mono text-xs"
                >
                    Dataset {truncateValue(item.datasetId)}
                </Link>
                {item.datasetItemId ? (
                    <span className="text-muted text-xs font-mono">Item {truncateValue(item.datasetItemId)}</span>
                ) : null}
            </div>
        )
    }

    if (item.datasetItemId) {
        return <span className="text-muted text-xs font-mono">Item {truncateValue(item.datasetItemId)}</span>
    }

    return <span className="text-muted">-</span>
}

function experimentsTableColumns(
    selectExperiment: (experimentId: string) => void,
    searchParams: Record<string, unknown>
): LemonTableColumns<OfflineExperiment> {
    return [
        {
            title: 'Experiment',
            key: 'experimentId',
            render: (_, experiment) => (
                <Link
                    to={
                        combineUrl(urls.llmAnalyticsOfflineEvaluationExperiment(experiment.experimentId), searchParams)
                            .url
                    }
                >
                    <EntityNameCell name={experiment.experimentName} id={experiment.experimentId} />
                </Link>
            ),
            sorter: (left, right) =>
                (left.experimentName || left.experimentId).localeCompare(right.experimentName || right.experimentId),
        },
        {
            title: 'Items',
            key: 'itemsCount',
            dataIndex: 'itemsCount',
            sorter: (left, right) => left.itemsCount - right.itemsCount,
        },
        {
            title: 'Metric columns',
            key: 'metricPairsCount',
            dataIndex: 'metricPairsCount',
            sorter: (left, right) => left.metricPairsCount - right.metricPairsCount,
        },
        {
            title: 'Events',
            key: 'eventsCount',
            dataIndex: 'eventsCount',
            sorter: (left, right) => left.eventsCount - right.eventsCount,
        },
        {
            title: '',
            key: 'actions',
            align: 'right',
            render: (_, experiment) => (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => selectExperiment(experiment.experimentId)}
                    data-attr="offline-evals-open-experiment"
                >
                    Open
                </LemonButton>
            ),
        },
        {
            title: 'Last seen',
            key: 'lastSeenAt',
            render: (_, experiment) => <LastSeenCell value={experiment.lastSeenAt} />,
            sorter: (left, right) => compareLastSeenDesc(left.lastSeenAt, right.lastSeenAt),
        },
    ]
}

function itemTableColumns(metricColumns: OfflineMetricColumn[]): LemonTableColumns<OfflineExperimentItem> {
    const baseColumns: LemonTableColumns<OfflineExperimentItem> = [
        {
            title: 'Item',
            key: 'itemId',
            render: (_, item) => <EntityNameCell name={item.itemName} id={item.itemId} />,
            sorter: (left, right) => (left.itemName || left.itemId).localeCompare(right.itemName || right.itemId),
        },
        {
            title: 'Dataset',
            key: 'source',
            render: (_, item) => <SourceCell item={item} />,
        },
        {
            title: 'Input',
            key: 'input',
            render: (_, item) => <PreviewCell value={item.input} />,
        },
        {
            title: 'Output',
            key: 'output',
            render: (_, item) => <PreviewCell value={item.output} />,
        },
        {
            title: 'Expected',
            key: 'expected',
            render: (_, item) => <PreviewCell value={item.expected} />,
        },
    ]

    const dynamicMetricColumns: LemonTableColumns<OfflineExperimentItem> = metricColumns.map((metricColumn) => ({
        title: (
            <div className="whitespace-nowrap">
                <span>{metricColumn.metricName}</span>
                <span className="text-muted text-xs ml-1">v{metricColumn.metricVersion}</span>
            </div>
        ),
        key: `metric-${metricColumn.key}`,
        render: (_, item) => <MetricCell value={item.metrics[metricColumn.key]} />,
    }))

    const lastSeenColumn: LemonTableColumns<OfflineExperimentItem> = [
        {
            title: 'Last seen',
            key: 'lastSeenAt',
            render: (_, item) => <LastSeenCell value={item.lastSeenAt} />,
            sorter: (left, right) => compareLastSeenDesc(left.lastSeenAt, right.lastSeenAt),
        },
    ]

    return [...baseColumns, ...dynamicMetricColumns, ...lastSeenColumn]
}

export function OfflineEvaluationsTab({ tabId }: { tabId?: string }): JSX.Element {
    const logic = useMountedLogic(offlineEvaluationsLogic({ tabId }))
    const { searchParams } = useValues(router)

    const {
        selectedExperiment,
        selectedExperimentId,
        selectedExperimentData,
        offlineDateFilter,
        filteredOfflineExperiments,
        offlineExperimentsFilter,
        filteredOfflineExperimentItems,
        offlineExperimentItemsFilter,
        offlineMetricColumns,
        offlineExperimentsLoading,
        selectedExperimentDataLoading,
    } = useValues(logic)

    const {
        refreshOfflineEvaluations,
        setOfflineDates,
        setOfflineExperimentsFilter,
        setOfflineExperimentItemsFilter,
        selectExperiment,
        clearSelectedExperiment,
    } = useActions(logic)
    const selectedExperimentName =
        selectedExperiment?.experimentName ??
        selectedExperimentData.items.find((item) => item.experimentName)?.experimentName ??
        null
    const selectedExperimentTitle = selectedExperimentName || selectedExperimentId

    if (!selectedExperimentId) {
        return (
            <div className="space-y-4">
                <div className="flex items-start justify-between gap-2">
                    <div>
                        <h2 className="text-xl font-semibold">Offline evals</h2>
                        <p className="text-muted">
                            Explore offline experiments from <code>$ai_evaluation</code> events grouped by experiment
                            ID.
                        </p>
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={refreshOfflineEvaluations}
                        loading={offlineExperimentsLoading}
                    >
                        Refresh
                    </LemonButton>
                </div>

                <LemonInput
                    type="search"
                    value={offlineExperimentsFilter}
                    onChange={setOfflineExperimentsFilter}
                    placeholder="Search experiment IDs or names..."
                    prefix={<IconSearch />}
                    className="max-w-sm"
                    data-attr="offline-evals-experiment-search"
                />

                <DateFilter
                    dateFrom={offlineDateFilter.dateFrom}
                    dateTo={offlineDateFilter.dateTo}
                    onChange={setOfflineDates}
                />

                <LemonTable
                    columns={experimentsTableColumns(selectExperiment, searchParams)}
                    dataSource={filteredOfflineExperiments}
                    loading={offlineExperimentsLoading}
                    rowKey="experimentId"
                    pagination={{ pageSize: 50 }}
                    nouns={['experiment', 'experiments']}
                    emptyState={<div className="text-center py-8 text-muted">No offline experiments found.</div>}
                />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex items-start justify-between gap-2">
                <div className="space-y-2">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        onClick={clearSelectedExperiment}
                        data-attr="offline-evals-back"
                    >
                        Back to experiments
                    </LemonButton>
                    <div>
                        <h2 className="text-xl font-semibold">{selectedExperimentTitle}</h2>
                        {selectedExperimentName ? (
                            <p className="text-muted text-xs font-mono">{selectedExperimentId}</p>
                        ) : null}
                        <p className="text-muted">
                            Showing items grouped by <code>$ai_experiment_item_id</code> with one column per metric
                            name/version pair.
                        </p>
                    </div>
                    {selectedExperiment ? (
                        <div className="text-sm text-muted flex flex-wrap gap-4">
                            <span>{selectedExperiment.itemsCount} items</span>
                            <span>{selectedExperiment.metricPairsCount} metric columns</span>
                            <span>{selectedExperiment.eventsCount} events</span>
                        </div>
                    ) : null}
                </div>

                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={refreshOfflineEvaluations}
                    loading={selectedExperimentDataLoading}
                >
                    Refresh
                </LemonButton>
            </div>

            <LemonInput
                type="search"
                value={offlineExperimentItemsFilter}
                onChange={setOfflineExperimentItemsFilter}
                placeholder="Search item ID, names, trace, dataset, content, or reasoning..."
                prefix={<IconSearch />}
                className="max-w-md"
                data-attr="offline-evals-item-search"
            />

            <div className="overflow-x-auto">
                <LemonTable
                    columns={itemTableColumns(offlineMetricColumns)}
                    dataSource={filteredOfflineExperimentItems}
                    loading={selectedExperimentDataLoading}
                    rowKey="itemId"
                    pagination={{ pageSize: 50 }}
                    nouns={['experiment item', 'experiment items']}
                    emptyState={<div className="text-center py-8 text-muted">No items found for this experiment.</div>}
                />
            </div>
        </div>
    )
}
