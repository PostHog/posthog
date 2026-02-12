import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import React, { useMemo } from 'react'

import { LemonBanner, LemonButton, LemonTab, LemonTabs, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { EventDetails } from 'scenes/activity/explore/EventDetails'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { EditCustomProductsModal } from '~/layout/panel-layout/PinnedFolder/EditCustomProductsModal'
import { editCustomProductsModalLogic } from '~/layout/panel-layout/PinnedFolder/editCustomProductsModalLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, DashboardPlacement, EventType } from '~/types'

import { LLMAnalyticsErrors } from './LLMAnalyticsErrors'
import { LLMAnalyticsPlaygroundScene } from './LLMAnalyticsPlaygroundScene'
import { LLMAnalyticsReloadAction } from './LLMAnalyticsReloadAction'
import { LLMAnalyticsSessionsScene } from './LLMAnalyticsSessionsScene'
import { LLMAnalyticsSetupPrompt } from './LLMAnalyticsSetupPrompt'
import { LLMAnalyticsTraces } from './LLMAnalyticsTracesScene'
import { LLMAnalyticsUsers } from './LLMAnalyticsUsers'
import { useSortableColumns } from './hooks/useSortableColumns'
import { llmAnalyticsColumnRenderers } from './llmAnalyticsColumnRenderers'
import { LLM_ANALYTICS_DATA_COLLECTION_NODE_ID, llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsDashboardLogic } from './tabs/llmAnalyticsDashboardLogic'
import { getDefaultGenerationsColumns, llmAnalyticsGenerationsLogic } from './tabs/llmAnalyticsGenerationsLogic'
import { truncateValue } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsScene,
    logic: llmAnalyticsSharedLogic,
    productKey: ProductKey.LLM_ANALYTICS,
}

const Filters = ({ hidePropertyFilters = false }: { hidePropertyFilters?: boolean }): JSX.Element => {
    const { dashboardDateFilter, dateFilter, shouldFilterTestAccounts, propertyFilters, activeTab } =
        useValues(llmAnalyticsSharedLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsSharedLogic)
    const { generationsQuery } = useValues(llmAnalyticsGenerationsLogic)
    const { selectedDashboardId } = useValues(llmAnalyticsDashboardLogic)

    const dateFrom = activeTab === 'dashboard' ? dashboardDateFilter.dateFrom : dateFilter.dateFrom
    const dateTo = activeTab === 'dashboard' ? dashboardDateFilter.dateTo : dateFilter.dateTo

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
            {activeTab === 'dashboard' && selectedDashboardId && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton type="secondary" size="small" to={urls.dashboard(selectedDashboardId)}>
                        Edit dashboard
                    </LemonButton>
                </AccessControlAction>
            )}
            <LLMAnalyticsReloadAction />
        </div>
    )
}

function LLMAnalyticsDashboard(): JSX.Element {
    const { dashboardDateFilter, propertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { selectedDashboardId, availableDashboardsLoading } = useValues(llmAnalyticsDashboardLogic)

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
            <div className="@container/dashboard" data-attr="llm-analytics-costs">
                <Filters />

                {availableDashboardsLoading || !selectedDashboardId ? (
                    <div className="text-center p-8">
                        <Spinner />
                    </div>
                ) : (
                    <Dashboard id={selectedDashboardId.toString()} placement={DashboardPlacement.Builtin} />
                )}
            </div>
        </LLMAnalyticsSetupPrompt>
    )
}

function LLMAnalyticsGenerations(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsSharedLogic)
    const { propertyFilters: currentPropertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { setGenerationsColumns, toggleGenerationExpanded, setGenerationsSort } =
        useActions(llmAnalyticsGenerationsLogic)
    const { generationsQuery, expandedGenerationIds, loadedTraces, generationsSort } =
        useValues(llmAnalyticsGenerationsLogic)
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

const DEFAULT_DOCS_URL = 'https://posthog.com/docs/llm-analytics/installation'
const DOCS_URLS_BY_TAB: Record<string, string> = {
    traces: 'https://posthog.com/docs/llm-analytics/traces',
    generations: 'https://posthog.com/docs/llm-analytics/generations',
    sessions: 'https://posthog.com/docs/llm-analytics/sessions',
    errors: 'https://posthog.com/docs/llm-analytics/errors',
}

const TAB_DESCRIPTIONS: Record<string, string> = {
    dashboard: 'Overview of your LLM usage, costs, and performance metrics.',
    traces: 'Explore end-to-end traces of your LLM interactions.',
    generations: 'View individual LLM generations and their details.',
    users: 'Understand how users are interacting with your LLM features.',
    errors: 'Monitor and debug errors in your LLM pipeline.',
    sessions: 'Analyze user sessions containing LLM interactions.',
    playground: 'Test and experiment with LLM prompts in a sandbox environment.',
}

export function LLMAnalyticsScene(): JSX.Element {
    const { activeTab } = useValues(llmAnalyticsSharedLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)

    const { push } = useActions(router)
    const { toggleProduct, openModal: openEditCustomProductsModal } = useActions(editCustomProductsModalLogic)

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
                <LLMAnalyticsSetupPrompt thing="trace">
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

    tabs.push({
        key: 'errors',
        label: 'Errors',
        content: (
            <LLMAnalyticsSetupPrompt>
                <LLMAnalyticsErrors />
            </LLMAnalyticsSetupPrompt>
        ),
        link: combineUrl(urls.llmAnalyticsErrors(), searchParams).url,
        'data-attr': 'errors-tab',
    })

    // TODO: Once we remove FF, should add to the shortcuts list at the top of the component
    if (
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SESSIONS_VIEW] ||
        featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
    ) {
        tabs.push({
            key: 'sessions',
            label: 'Sessions',
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

    const availableItemsInSidebar = useMemo(() => {
        return [
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_CLUSTERS_TAB] ? (
                <Link to={urls.llmAnalyticsClusters()} onClick={() => toggleProduct('Clusters', true)}>
                    clusters
                </Link>
            ) : null,
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DATASETS] ? (
                <Link to={urls.llmAnalyticsDatasets()} onClick={() => toggleProduct('Datasets', true)}>
                    datasets
                </Link>
            ) : null,
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS] ? (
                <Link to={urls.llmAnalyticsEvaluations()} onClick={() => toggleProduct('Evaluations', true)}>
                    evaluations
                </Link>
            ) : null,
            featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_PROMPTS] ? (
                <Link to={urls.llmAnalyticsPrompts()} onClick={() => toggleProduct('Prompts', true)}>
                    prompts
                </Link>
            ) : null,
        ].filter(Boolean) as JSX.Element[]
    }, [featureFlags, toggleProduct])

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.LLMAnalytics].name}
                    description={TAB_DESCRIPTIONS[activeTab] || sceneConfigurations[Scene.LLMAnalytics].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.LLMAnalytics].iconType || 'default_icon_type',
                    }}
                    actions={
                        <>
                            <LemonButton
                                to={DOCS_URLS_BY_TAB[activeTab] || DEFAULT_DOCS_URL}
                                type="secondary"
                                targetBlank
                                size="small"
                            >
                                Documentation
                            </LemonButton>
                        </>
                    }
                />

                {availableItemsInSidebar.length > 0 ? (
                    <>
                        <LemonBanner type="info" className="mb-2" dismissKey="llm-analytics-sidebar-moved-banner">
                            We've moved{' '}
                            {availableItemsInSidebar.map((el, i) => (
                                <React.Fragment key={i}>
                                    {i > 0 && ', '}
                                    {el}
                                </React.Fragment>
                            ))}{' '}
                            out of LLM Analytics and into their own apps. You can access them by clicking in the links
                            above, or by clicking "All apps" in the sidebar. You can also customize your sidebar{' '}
                            <Link onClick={openEditCustomProductsModal}>here</Link>.
                        </LemonBanner>
                        <EditCustomProductsModal />
                    </>
                ) : null}

                <LemonTabs activeKey={activeTab} data-attr="llm-analytics-tabs" tabs={tabs} sceneInset />
            </SceneContent>
        </BindLogic>
    )
}
