import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import React from 'react'

import { IconCopy, IconPencil, IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSwitch,
    LemonTab,
    LemonTable,
    LemonTabs,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyDuration, objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { EventDetails } from 'scenes/activity/explore/EventDetails'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import { DashboardPlacement, EventType } from '~/types'

import { LLMAnalyticsErrors } from './LLMAnalyticsErrors'
import { LLMAnalyticsPlaygroundScene } from './LLMAnalyticsPlaygroundScene'
import { LLMAnalyticsReloadAction } from './LLMAnalyticsReloadAction'
import { LLMAnalyticsSessionsScene } from './LLMAnalyticsSessionsScene'
import { LLMAnalyticsSetupPrompt } from './LLMAnalyticsSetupPrompt'
import { LLMAnalyticsTraces } from './LLMAnalyticsTracesScene'
import { LLMAnalyticsUsers } from './LLMAnalyticsUsers'
import { LLMAnalyticsDatasetsScene } from './datasets/LLMAnalyticsDatasetsScene'
import { EvaluationTemplatesEmptyState } from './evaluations/EvaluationTemplates'
import {
    EvaluationMetrics,
    PASS_RATE_SUCCESS_THRESHOLD,
    PASS_RATE_WARNING_THRESHOLD,
} from './evaluations/components/EvaluationMetrics'
import { EvaluationStats, evaluationMetricsLogic } from './evaluations/evaluationMetricsLogic'
import { llmEvaluationsLogic } from './evaluations/llmEvaluationsLogic'
import { EvaluationConfig } from './evaluations/types'
import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsColumnRenderers } from './llmAnalyticsColumnRenderers'
import {
    LLM_ANALYTICS_DATA_COLLECTION_NODE_ID,
    getDefaultGenerationsColumns,
    llmAnalyticsLogic,
} from './llmAnalyticsLogic'
import { LLMPromptsScene } from './prompts/LLMPromptsScene'
import { LLMProviderKeysSettings } from './settings/LLMProviderKeysSettings'
import { TrialUsageMeter } from './settings/TrialUsageMeter'
import { truncateValue } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsScene,
    logic: llmAnalyticsLogic,
}

const Filters = ({ hidePropertyFilters = false }: { hidePropertyFilters?: boolean }): JSX.Element => {
    const {
        dashboardDateFilter,
        dateFilter,
        shouldFilterTestAccounts,
        generationsQuery,
        propertyFilters,
        activeTab,
        selectedDashboardId,
    } = useValues(llmAnalyticsLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const dateFrom = activeTab === 'dashboard' ? dashboardDateFilter.dateFrom : dateFilter.dateFrom
    const dateTo = activeTab === 'dashboard' ? dashboardDateFilter.dateTo : dateFilter.dateTo

    const useCustomizableDashboard =
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]

    return (
        <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            {!hidePropertyFilters && (
                <>
                    <PropertyFilters
                        propertyFilters={propertyFilters}
                        taxonomicGroupTypes={generationsQuery.showPropertyFilter as TaxonomicFilterGroupType[]}
                        onChange={setPropertyFilters}
                        pageKey="llm-analytics"
                    />
                    <div className="flex-1" />
                    <TestAccountFilterSwitch
                        checked={shouldFilterTestAccounts}
                        onChange={setShouldFilterTestAccounts}
                    />
                </>
            )}
            {hidePropertyFilters && <div className="flex-1" />}
            {activeTab === 'dashboard' && useCustomizableDashboard && selectedDashboardId && (
                <LemonButton type="secondary" size="small" to={urls.dashboard(selectedDashboardId)}>
                    Edit dashboard
                </LemonButton>
            )}
            <LLMAnalyticsReloadAction />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(llmAnalyticsLogic)

    return (
        <div className="mt-2 grid grid-cols-1 @xl/dashboard:grid-cols-2 @4xl/dashboard:grid-cols-6 gap-4">
            {tiles.map(({ title, description, query, context }, i) => (
                <QueryCard
                    key={i}
                    attachTo={llmAnalyticsLogic}
                    title={title}
                    description={description}
                    query={{ kind: NodeKind.InsightVizNode, source: query } as InsightVizNode}
                    context={context}
                    sceneSource="llm-analytics"
                    className={clsx(
                        'h-96',
                        /* Second row is the only one to have 2 tiles in the xl layout */
                        i < 3 || i >= 5 ? '@4xl/dashboard:col-span-2' : '@4xl/dashboard:col-span-3'
                    )}
                />
            ))}
        </div>
    )
}

function LLMAnalyticsDashboard(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { selectedDashboardId, availableDashboardsLoading, dashboardDateFilter, propertyFilters } =
        useValues(llmAnalyticsLogic)

    const useCustomizableDashboard =
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
    const dashboardLogicInstance = React.useMemo(
        () =>
            selectedDashboardId
                ? dashboardLogic({ id: selectedDashboardId, placement: DashboardPlacement.Builtin })
                : null,
        [selectedDashboardId]
    )

    const fallbackLogicInstance = React.useMemo(
        () => dashboardLogic({ id: 0, placement: DashboardPlacement.Builtin }),
        []
    )
    const dashboardActions = useActions(dashboardLogicInstance || fallbackLogicInstance)
    const setExternalFilters =
        dashboardLogicInstance && dashboardActions?.setExternalFilters ? dashboardActions.setExternalFilters : () => {}

    // Set filters using useLayoutEffect to ensure they're set before Dashboard's afterMount event fires
    React.useLayoutEffect(() => {
        if (selectedDashboardId && setExternalFilters) {
            setExternalFilters({
                date_from: dashboardDateFilter.dateFrom,
                date_to: dashboardDateFilter.dateTo,
                properties: propertyFilters.length > 0 ? propertyFilters : null,
            })
        }
    }, [dashboardDateFilter, propertyFilters, selectedDashboardId, setExternalFilters])

    return (
        <LLMAnalyticsSetupPrompt>
            <div className="@container/dashboard">
                <Filters />

                {useCustomizableDashboard ? (
                    availableDashboardsLoading || !selectedDashboardId ? (
                        <div className="text-center p-8">
                            <Spinner />
                        </div>
                    ) : (
                        <Dashboard id={selectedDashboardId.toString()} placement={DashboardPlacement.Builtin} />
                    )
                ) : (
                    <Tiles />
                )}
            </div>
        </LLMAnalyticsSetupPrompt>
    )
}

function LLMAnalyticsGenerations(): JSX.Element {
    const {
        setDates,
        setShouldFilterTestAccounts,
        setPropertyFilters,
        setGenerationsColumns,
        toggleGenerationExpanded,
        setGenerationsSort,
    } = useActions(llmAnalyticsLogic)
    const {
        generationsQuery,
        propertyFilters: currentPropertyFilters,
        expandedGenerationIds,
        loadedTraces,
        generationsSort,
    } = useValues(llmAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { renderSortableColumnTitle } = useSortableColumns(generationsSort, setGenerationsSort)

    // Helper to safely extract uuid and traceId from a result row based on current column configuration
    const getRowIds = (result: unknown): { uuid: string; traceId: string } | null => {
        if (!Array.isArray(result) || !isEventsQuery(generationsQuery.source)) {
            return null
        }

        const columns =
            generationsQuery.source.select ||
            getDefaultGenerationsColumns(!!featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT])

        const uuidIndex = columns.findIndex((col) => col === 'uuid')
        const traceIdIndex = columns.findIndex((col) => col === 'properties.$ai_trace_id')

        if (uuidIndex < 0 || traceIdIndex < 0) {
            return null
        }

        const uuid = result[uuidIndex]
        const traceId = result[traceIdIndex]

        if (typeof uuid === 'string' && typeof traceId === 'string') {
            return { uuid, traceId }
        }

        return null
    }

    return (
        <DataTable
            query={{
                ...generationsQuery,
                showSavedFilters: true,
                defaultColumns: getDefaultGenerationsColumns(
                    !!featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT]
                ),
            }}
            setQuery={(query) => {
                if (!isEventsQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                setDates(query.source.after || null, query.source.before || null)
                setShouldFilterTestAccounts(query.source.filterTestAccounts || false)

                const newPropertyFilters = query.source.properties || []
                if (!objectsEqual(newPropertyFilters, currentPropertyFilters)) {
                    setPropertyFilters(newPropertyFilters)
                }

                if (query.source.select) {
                    setGenerationsColumns(query.source.select)
                }
            }}
            context={{
                emptyStateHeading: 'There were no generations in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    uuid: {
                        title: 'ID',
                        render: ({ record, value }) => {
                            if (!value || typeof value !== 'string') {
                                return null
                            }

                            const ids = getRowIds(record)
                            const visualValue = truncateValue(value)

                            return !ids ? (
                                <strong>{visualValue}</strong>
                            ) : (
                                <strong>
                                    <Tooltip title={value}>
                                        <Link
                                            to={`/llm-analytics/traces/${ids.traceId}?event=${value}`}
                                            data-attr="generation-id-link"
                                        >
                                            {visualValue}
                                        </Link>
                                    </Tooltip>
                                </strong>
                            )
                        },
                    },
                    person: llmAnalyticsColumnRenderers.person,
                    "f'{properties.$ai_model}' -- Model": {
                        renderTitle: () => renderSortableColumnTitle('properties.$ai_model', 'Model'),
                    },
                    "f'{round(toFloat(properties.$ai_latency), 2)} s' -- Latency": {
                        renderTitle: () => renderSortableColumnTitle('properties.$ai_latency', 'Latency'),
                    },
                    "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Cost": {
                        renderTitle: () => (
                            <Tooltip title="Cost of this generation">
                                {renderSortableColumnTitle('properties.$ai_total_cost_usd', 'Cost')}
                            </Tooltip>
                        ),
                    },
                    timestamp: {
                        renderTitle: () => renderSortableColumnTitle('timestamp', 'Time'),
                    },
                },
                expandable: {
                    expandedRowRender: function renderExpandedGeneration({ result }: DataTableRow) {
                        const ids = getRowIds(result)

                        if (!ids) {
                            return (
                                <div className="p-4 text-danger">
                                    Cannot expand: required columns (uuid, properties.$ai_trace_id) are missing. Please
                                    reset your column configuration.
                                </div>
                            )
                        }

                        const trace = loadedTraces[ids.traceId]
                        const event = trace?.events.find((e) => e.id === ids.uuid)

                        if (!trace) {
                            return (
                                <div className="p-4">
                                    <Spinner />
                                </div>
                            )
                        }

                        if (!event) {
                            return <div className="p-4">Event not found in trace</div>
                        }

                        // Convert LLMTraceEvent to EventType format for EventDetails
                        const eventForDetails: EventType = {
                            id: event.id,
                            uuid: event.id,
                            distinct_id: '',
                            properties: event.properties,
                            event: event.event,
                            timestamp: event.createdAt,
                            elements: [],
                        }

                        return (
                            <div className="pt-2 px-4 pb-4">
                                <EventDetails event={eventForDetails} />
                            </div>
                        )
                    },
                    rowExpandable: ({ result }: DataTableRow) => !!getRowIds(result),
                    isRowExpanded: ({ result }: DataTableRow) => {
                        const ids = getRowIds(result)
                        return !!ids && expandedGenerationIds.has(ids.uuid)
                    },
                    onRowExpand: ({ result }: DataTableRow) => {
                        const ids = getRowIds(result)
                        if (ids) {
                            toggleGenerationExpanded(ids.uuid, ids.traceId)
                        }
                    },
                    onRowCollapse: ({ result }: DataTableRow) => {
                        const ids = getRowIds(result)
                        if (ids) {
                            toggleGenerationExpanded(ids.uuid, ids.traceId)
                        }
                    },
                    noIndent: true,
                },
            }}
            uniqueKey="llm-analytics-generations"
        />
    )
}

function LLMAnalyticsEvaluations(): JSX.Element {
    return (
        <BindLogic logic={llmEvaluationsLogic} props={{}}>
            <BindLogic logic={evaluationMetricsLogic} props={{}}>
                <LLMAnalyticsEvaluationsContent />
            </BindLogic>
        </BindLogic>
    )
}

function LLMAnalyticsEvaluationsContent(): JSX.Element {
    const { evaluations, filteredEvaluations, evaluationsLoading, evaluationsFilter } = useValues(llmEvaluationsLogic)
    const { setEvaluationsFilter, toggleEvaluationEnabled, duplicateEvaluation, loadEvaluations } =
        useActions(llmEvaluationsLogic)
    const { evaluationsWithMetrics } = useValues(evaluationMetricsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { push } = useActions(router)

    const filteredEvaluationsWithMetrics = evaluationsWithMetrics.filter((evaluation: EvaluationConfig) =>
        filteredEvaluations.some((filtered) => filtered.id === evaluation.id)
    )

    // Show templates when there are no evaluations at all (not just filtered empty)
    if (!evaluationsLoading && evaluations.length === 0) {
        return <EvaluationTemplatesEmptyState />
    }

    const columns: LemonTableColumns<EvaluationConfig> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, evaluation) => (
                <div className="flex flex-col">
                    <Link to={urls.llmAnalyticsEvaluation(evaluation.id)} className="font-semibold text-primary">
                        {evaluation.name}
                    </Link>
                    {evaluation.description && <div className="text-muted text-sm">{evaluation.description}</div>}
                </div>
            ),
            sorter: (a, b) => a.name.localeCompare(b.name),
        },
        {
            title: 'Status',
            key: 'enabled',
            render: (_, evaluation) => (
                <div className="flex items-center gap-2">
                    <LemonSwitch
                        checked={evaluation.enabled}
                        onChange={() => toggleEvaluationEnabled(evaluation.id)}
                        size="small"
                        data-attr="toggle-evaluation-enabled"
                    />
                    <span className={evaluation.enabled ? 'text-success' : 'text-muted'}>
                        {evaluation.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                </div>
            ),
            sorter: (a, b) => Number(b.enabled) - Number(a.enabled),
        },
        {
            title: 'Prompt',
            key: 'prompt',
            render: (_, evaluation) => (
                <div className="max-w-md">
                    <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                        {evaluation.evaluation_config.prompt || '(No prompt)'}
                    </div>
                </div>
            ),
        },
        {
            title: 'Triggers',
            key: 'conditions',
            render: (_, evaluation) => (
                <div className="flex flex-wrap gap-1">
                    {evaluation.conditions.map((condition) => (
                        <LemonTag key={condition.id} type="option">
                            {condition.rollout_percentage}%
                            {condition.properties.length > 0 &&
                                ` when ${condition.properties.length} condition${condition.properties.length !== 1 ? 's' : ''}`}
                        </LemonTag>
                    ))}
                    {evaluation.conditions.length === 0 && <span className="text-muted text-sm">No triggers</span>}
                </div>
            ),
        },
        {
            title: 'Recent',
            key: 'recent_stats',
            render: (_, evaluation: EvaluationConfig & { stats?: EvaluationStats }) => {
                const stats = evaluation.stats
                if (!stats || stats.runs_count === 0) {
                    return <span className="text-muted text-sm">No runs</span>
                }

                const passRateColor =
                    stats.pass_rate >= PASS_RATE_SUCCESS_THRESHOLD
                        ? 'text-success'
                        : stats.pass_rate >= PASS_RATE_WARNING_THRESHOLD
                          ? 'text-warning'
                          : 'text-danger'

                return (
                    <div className="flex flex-col items-center">
                        <div className="text-sm">
                            {stats.runs_count} run{stats.runs_count !== 1 ? 's' : ''}
                        </div>
                        <div className={`font-semibold ${passRateColor}`}>{stats.pass_rate}%</div>
                    </div>
                )
            },
        },
        {
            title: 'Runs',
            key: 'total_runs',
            render: (_, evaluation) => (
                <div className="flex flex-col items-center">
                    <div className="font-semibold">{evaluation.total_runs}</div>
                    {evaluation.last_run_at && (
                        <div className="text-muted text-xs">Last: {humanFriendlyDuration(evaluation.last_run_at)}</div>
                    )}
                </div>
            ),
            sorter: (a, b) => b.total_runs - a.total_runs,
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_, evaluation) => (
                <More
                    overlay={
                        <>
                            <LemonButton
                                icon={<IconPencil />}
                                onClick={() => push(urls.llmAnalyticsEvaluation(evaluation.id))}
                                fullWidth
                            >
                                Edit
                            </LemonButton>
                            <LemonButton
                                icon={<IconCopy />}
                                onClick={() => duplicateEvaluation(evaluation.id)}
                                fullWidth
                            >
                                Duplicate
                            </LemonButton>
                            <LemonButton
                                icon={<IconTrash />}
                                status="danger"
                                onClick={() => {
                                    deleteWithUndo({
                                        endpoint: `environments/${currentTeamId}/evaluations`,
                                        object: evaluation,
                                        callback: () => loadEvaluations(),
                                    })
                                }}
                                fullWidth
                            >
                                Delete
                            </LemonButton>
                        </>
                    }
                />
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <Filters hidePropertyFilters />

            <TrialUsageMeter showSettingsLink />

            <LemonBanner type="info" dismissKey="evals-billing-notice">
                Each evaluation run counts as an LLM analytics event.
            </LemonBanner>

            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Evaluations</h2>
                    <p className="text-muted">
                        Configure evaluation prompts and triggers to automatically assess your LLM generations.
                    </p>
                </div>
                <AppShortcut
                    name="NewLLMEvaluation"
                    keybind={[keyBinds.new]}
                    intent="Create evaluation"
                    interaction="click"
                    scope={Scene.LLMAnalytics}
                >
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={urls.llmAnalyticsEvaluationTemplates()}
                        data-attr="create-evaluation-button"
                        tooltip="Create evaluation"
                    >
                        Create Evaluation
                    </LemonButton>
                </AppShortcut>
            </div>

            {/* Metrics Visualization */}
            <EvaluationMetrics />

            {/* Search */}
            <div className="flex items-center gap-2">
                <AppShortcut
                    name="SearchLLMEvaluations"
                    keybind={[keyBinds.filter]}
                    intent="Search evaluations"
                    interaction="click"
                    scope={Scene.LLMAnalytics}
                >
                    <LemonInput
                        type="search"
                        placeholder="Search evaluations..."
                        value={evaluationsFilter}
                        data-attr="evaluations-search-input"
                        onChange={setEvaluationsFilter}
                        prefix={<IconSearch />}
                        className="max-w-sm"
                    />
                </AppShortcut>
            </div>

            {/* Table */}
            <LemonTable
                columns={columns}
                dataSource={filteredEvaluationsWithMetrics}
                loading={evaluationsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 50,
                }}
                nouns={['evaluation', 'evaluations']}
            />
        </div>
    )
}

export function LLMAnalyticsScene(): JSX.Element {
    const { activeTab } = useValues(llmAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)
    const { push } = useActions(router)

    // Tab switching shortcuts
    useAppShortcut({
        name: 'LLMAnalyticsTab1',
        keybind: [keyBinds.tab1],
        intent: 'Go to Dashboard',
        interaction: 'function',
        callback: () => push(combineUrl(urls.llmAnalyticsDashboard(), searchParams).url),
        scope: Scene.LLMAnalytics,
    })
    useAppShortcut({
        name: 'LLMAnalyticsTab2',
        keybind: [keyBinds.tab2],
        intent: 'Go to Traces',
        interaction: 'function',
        callback: () => push(combineUrl(urls.llmAnalyticsTraces(), searchParams).url),
        scope: Scene.LLMAnalytics,
    })
    useAppShortcut({
        name: 'LLMAnalyticsTab3',
        keybind: [keyBinds.tab3],
        intent: 'Go to Generations',
        interaction: 'function',
        callback: () => push(combineUrl(urls.llmAnalyticsGenerations(), searchParams).url),
        scope: Scene.LLMAnalytics,
    })
    useAppShortcut({
        name: 'LLMAnalyticsTab4',
        keybind: [keyBinds.tab4],
        intent: 'Go to Users',
        interaction: 'function',
        callback: () => push(combineUrl(urls.llmAnalyticsUsers(), searchParams).url),
        scope: Scene.LLMAnalytics,
    })

    const tabs: LemonTab<string>[] = [
        {
            key: 'dashboard',
            label: 'Dashboard',
            content: <LLMAnalyticsDashboard />,
            link: combineUrl(urls.llmAnalyticsDashboard(), searchParams).url,
            'data-attr': 'dashboard-tab',
        },
        {
            key: 'traces',
            label: 'Traces',
            content: (
                <LLMAnalyticsSetupPrompt>
                    <LLMAnalyticsTraces />
                </LLMAnalyticsSetupPrompt>
            ),
            link: combineUrl(urls.llmAnalyticsTraces(), searchParams).url,
            'data-attr': 'traces-tab',
        },
        {
            key: 'generations',
            label: 'Generations',
            content: (
                <LLMAnalyticsSetupPrompt>
                    <LLMAnalyticsGenerations />
                </LLMAnalyticsSetupPrompt>
            ),
            link: combineUrl(urls.llmAnalyticsGenerations(), searchParams).url,
            'data-attr': 'generations-tab',
        },
        {
            key: 'users',
            label: 'Users',
            content: (
                <LLMAnalyticsSetupPrompt>
                    <LLMAnalyticsUsers />
                </LLMAnalyticsSetupPrompt>
            ),
            link: combineUrl(urls.llmAnalyticsUsers(), searchParams).url,
            'data-attr': 'users-tab',
        },
    ]

    if (
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_ERRORS_TAB] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
    ) {
        tabs.push({
            key: 'errors',
            label: (
                <>
                    Errors{' '}
                    <LemonTag className="ml-1" type="warning">
                        Beta
                    </LemonTag>
                </>
            ),
            content: (
                <LLMAnalyticsSetupPrompt>
                    <LLMAnalyticsErrors />
                </LLMAnalyticsSetupPrompt>
            ),
            link: combineUrl(urls.llmAnalyticsErrors(), searchParams).url,
            'data-attr': 'errors-tab',
        })
    }

    // TODO: Once we remove FF, should add to the shortcuts list at the top of the component
    if (
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSIONS_VIEW] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
    ) {
        tabs.push({
            key: 'sessions',
            label: (
                <>
                    Sessions{' '}
                    <LemonTag className="ml-1" type="warning">
                        Beta
                    </LemonTag>
                </>
            ),
            content: (
                <LLMAnalyticsSetupPrompt>
                    <LLMAnalyticsSessionsScene />
                </LLMAnalyticsSetupPrompt>
            ),
            link: combineUrl(urls.llmAnalyticsSessions(), searchParams).url,
            'data-attr': 'sessions-tab',
        })
    }

    // TODO: Once we are out of beta, should add to the shortcuts list at the top of the component
    tabs.push({
        key: 'playground',
        label: (
            <>
                Playground{' '}
                <LemonTag className="ml-1" type="warning">
                    Beta
                </LemonTag>
            </>
        ),
        content: <LLMAnalyticsPlaygroundScene />,
        link: combineUrl(urls.llmAnalyticsPlayground(), searchParams).url,
        'data-attr': 'playground-tab',
    })

    // TODO: Once we remove FF, should add to the shortcuts list at the top of the component
    if (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]) {
        tabs.push({
            key: 'evaluations',
            label: (
                <>
                    Evaluations{' '}
                    <LemonTag className="ml-1" type="completion">
                        Alpha
                    </LemonTag>
                </>
            ),
            content: <LLMAnalyticsEvaluations />,
            link: combineUrl('/llm-analytics/evaluations', searchParams).url,
            'data-attr': 'evaluations-tab',
        })
    }

    // TODO: Once we remove FF, should add to the shortcuts list at the top of the component
    if (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS]) {
        tabs.push({
            key: 'datasets',
            label: (
                <>
                    Datasets{' '}
                    <LemonTag className="ml-1" type="warning">
                        Beta
                    </LemonTag>
                </>
            ),
            content: <LLMAnalyticsDatasetsScene />,
            link: combineUrl(urls.llmAnalyticsDatasets(), searchParams).url,
            'data-attr': 'datasets-tab',
        })
    }

    // TODO: Once we remove FF, should add to the shortcuts list at the top of the component
    if (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_PROMPTS]) {
        tabs.push({
            key: 'prompts',
            label: (
                <>
                    Prompts{' '}
                    <LemonTag className="ml-1" type="completion">
                        Alpha
                    </LemonTag>
                </>
            ),
            content: <LLMPromptsScene />,
            link: combineUrl(urls.llmAnalyticsPrompts(), searchParams).url,
            'data-attr': 'prompts-tab',
        })
    }

    // TODO: Once we remove FF, should add to the shortcuts list at the top of the component
    if (featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS]) {
        tabs.push({
            key: 'settings',
            label: 'Settings',
            content: <LLMProviderKeysSettings />,
            link: combineUrl(urls.llmAnalyticsSettings(), searchParams).url,
            'data-attr': 'settings-tab',
        })
    }

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.LLMAnalytics].name}
                    description={sceneConfigurations[Scene.LLMAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.LLMAnalytics].iconType || 'default_icon_type',
                    }}
                    actions={
                        <>
                            <LemonButton
                                to="https://posthog.com/docs/llm-analytics/installation"
                                type="secondary"
                                targetBlank
                                size="small"
                            >
                                Documentation
                            </LemonButton>
                        </>
                    }
                />

                <LemonTabs activeKey={activeTab} data-attr="llm-analytics-tabs" tabs={tabs} sceneInset />
            </SceneContent>
        </BindLogic>
    )
}
