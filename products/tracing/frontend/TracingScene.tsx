import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ServiceMapPlaceholder } from './components/ServiceMapPlaceholder'
import { TraceSparkline } from './components/TraceSparkline'
import { TraceWaterfall } from './components/TraceWaterfall'
import { TracesList } from './components/TracesList'
import { MOCK_SERVICES } from './data/mockTraceData'
import { tracingFilterLogic } from './tracingFilterLogic'
import { TracingTab, tracingSceneLogic } from './tracingSceneLogic'

export const scene: SceneExport = {
    component: TracingScene,
    logic: tracingSceneLogic,
    productKey: ProductKey.TRACING,
}

export function TracingScene(): JSX.Element {
    const { activeTab, selectedTraceId, selectedTrace } = useValues(tracingSceneLogic)
    const { setActiveTab, setSelectedTraceId } = useActions(tracingSceneLogic)

    const { traces, searchQuery, serviceFilter, statusFilter, dateFrom, dateTo } = useValues(tracingFilterLogic)
    const { setSearchQuery, setServiceFilter, setStatusFilter, setDateFrom, setDateTo } = useActions(tracingFilterLogic)

    return (
        <SceneContent className="h-full flex flex-col grow">
            <SceneTitleSection
                name={sceneConfigurations[Scene.Tracing].name}
                description={sceneConfigurations[Scene.Tracing].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Tracing].iconType || 'default_icon_type',
                }}
            />

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as TracingTab)}
                tabs={[
                    { key: 'traces', label: 'Traces' },
                    { key: 'service-map', label: 'Service map' },
                ]}
            />

            {activeTab === 'traces' ? (
                <div className="flex flex-col gap-3 grow">
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonInput
                            type="search"
                            placeholder="Search traces..."
                            size="small"
                            className="w-60"
                            value={searchQuery}
                            onChange={setSearchQuery}
                        />
                        <LemonSelect
                            size="small"
                            placeholder="Service"
                            options={MOCK_SERVICES.map((s) => ({ value: s, label: s }))}
                            value={serviceFilter}
                            onChange={setServiceFilter}
                            allowClear
                        />
                        <LemonSelect
                            size="small"
                            placeholder="Status"
                            options={[
                                { value: 'ok', label: 'OK' },
                                { value: 'error', label: 'Error' },
                            ]}
                            value={statusFilter}
                            onChange={setStatusFilter}
                            allowClear
                        />
                        <DateFilter
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={(from, to) => {
                                setDateFrom(from ?? null)
                                setDateTo(to ?? null)
                            }}
                            size="small"
                        />
                    </div>

                    <TraceSparkline />

                    <div className="flex-1 min-h-0 overflow-auto">
                        <TracesList
                            traces={traces}
                            selectedTraceId={selectedTraceId}
                            onSelectTrace={setSelectedTraceId}
                        />
                    </div>

                    {selectedTrace && <TraceWaterfall trace={selectedTrace} />}
                </div>
            ) : (
                <div className="flex flex-col grow">
                    <ServiceMapPlaceholder />
                </div>
            )}
        </SceneContent>
    )
}
