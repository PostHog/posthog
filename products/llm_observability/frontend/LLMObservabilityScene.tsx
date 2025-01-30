import { IconArchive } from '@posthog/icons'
import { LemonBanner, LemonTabs, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'

import { LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID, llmObservabilityLogic } from './llmObservabilityLogic'
import { LLMObservabilityTraces } from './LLMObservabilityTracesScene'

export const scene: SceneExport = {
    component: LLMObservabilityScene,
}

const Filters = (): JSX.Element => {
    const { dashboardDateFilter, dateFilter, shouldFilterTestAccounts, generationsQuery, propertyFilters, activeTab } =
        useValues(llmObservabilityLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmObservabilityLogic)

    const dateFrom = activeTab === 'dashboard' ? dashboardDateFilter.dateFrom : dateFilter.dateFrom
    const dateTo = activeTab === 'dashboard' ? dashboardDateFilter.dateTo : dateFilter.dateTo

    return (
        <div className="flex gap-x-4 gap-y-2 items-center flex-wrap py-4 -mt-4 mb-4 border-b">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
            <PropertyFilters
                propertyFilters={propertyFilters}
                taxonomicGroupTypes={generationsQuery.showPropertyFilter as TaxonomicFilterGroupType[]}
                onChange={setPropertyFilters}
                pageKey="llm-observability"
            />
            <div className="flex-1" />
            <TestAccountFilterSwitch checked={shouldFilterTestAccounts} onChange={setShouldFilterTestAccounts} />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(llmObservabilityLogic)

    return (
        <div className="mt-2 grid grid-cols-1 @xl/dashboard:grid-cols-2 @4xl/dashboard:grid-cols-6 gap-4">
            {tiles.map(({ title, description, query, context }, i) => (
                <QueryCard
                    key={i}
                    title={title}
                    description={description}
                    query={{ kind: NodeKind.InsightVizNode, source: query } as InsightVizNode}
                    context={context}
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

const IngestionStatusCheck = (): JSX.Element | null => {
    const { hasSentAiGenerationEvent } = useValues(llmObservabilityLogic)
    if (hasSentAiGenerationEvent !== false) {
        return null
    }
    return (
        <LemonBanner type="warning" className="mt-2">
            <p>
                <strong>No LLM generation events have been detected!</strong>
            </p>
            <p>
                To use the LLM Observability product, please{' '}
                <Link to="https://posthog.com/docs/ai-engineering/observability">
                    instrument your LLM calls with the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
        </LemonBanner>
    )
}

function LLMObservabilityDashboard(): JSX.Element {
    return (
        <div className="@container/dashboard">
            <Filters />
            <Tiles />
        </div>
    )
}

function LLMObservabilityGenerations(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmObservabilityLogic)
    const { generationsQuery } = useValues(llmObservabilityLogic)

    return (
        <DataTable
            query={generationsQuery}
            setQuery={(query) => {
                if (!isEventsQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                setDates(query.source.after || null, query.source.before || null)
                setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                setPropertyFilters(query.source.properties || [])
            }}
            context={{
                emptyStateHeading: 'There were no generations in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
            }}
            uniqueKey="llm-observability-generations"
        />
    )
}

function LLMObservabilityNoEvents(): JSX.Element {
    return (
        <div className="w-full flex flex-col items-center justify-center">
            <div className="flex flex-col items-center justify-center max-w-md w-full">
                <IconArchive className="text-5xl mb-2 text-muted-alt" />
                <h2 className="text-xl leading-tight">We haven't detected any LLM generations yet</h2>
                <p className="text-sm text-center text-balance">
                    To use the LLM Observability product, please{' '}
                    <Link to="https://posthog.com/docs/ai-engineering/observability">
                        instrument your LLM calls with the PostHog SDK
                    </Link>{' '}
                </p>
            </div>
        </div>
    )
}

export function LLMObservabilityScene(): JSX.Element {
    const { activeTab, hasSentAiGenerationEvent } = useValues(llmObservabilityLogic)
    const { searchParams } = useValues(router)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID }}>
            <IngestionStatusCheck />
            <LemonTabs
                activeKey={activeTab}
                tabs={[
                    {
                        key: 'dashboard',
                        label: 'Dashboard',
                        content: <LLMObservabilityDashboard />,
                        link: combineUrl(urls.llmObservabilityDashboard(), searchParams).url,
                    },
                    {
                        key: 'traces',
                        label: 'Traces',
                        content: hasSentAiGenerationEvent ? <LLMObservabilityTraces /> : <LLMObservabilityNoEvents />,
                        link: combineUrl(urls.llmObservabilityTraces(), searchParams).url,
                    },
                    {
                        key: 'generations',
                        label: 'Generations',
                        content: hasSentAiGenerationEvent ? (
                            <LLMObservabilityGenerations />
                        ) : (
                            <LLMObservabilityNoEvents />
                        ),
                        link: combineUrl(urls.llmObservabilityGenerations(), searchParams).url,
                    },
                ]}
            />
        </BindLogic>
    )
}
