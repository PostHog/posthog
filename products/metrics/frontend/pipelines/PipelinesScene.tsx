import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { pipelinesFeaturePreviewGate } from '../featurePreviewGate'
import { pipelinesLogic } from './pipelinesLogic'
import { MetricsPipelineApi } from './types'

export const scene: SceneExport = {
    component: MetricsPipelinesScene,
    logic: pipelinesLogic,
    productKey: ProductKey.METRICS,
}

export function MetricsPipelinesScene(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={pipelinesFeaturePreviewGate}>
            <MetricsPipelinesSceneContent />
        </FeaturePreviewSceneGate>
    )
}

function MetricsPipelinesSceneContent(): JSX.Element {
    const { pipelines, pipelinesLoading } = useValues(pipelinesLogic)
    const { deletePipeline } = useActions(pipelinesLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pipelines"
                description="Live topology of your systems: nodes with health stats, edges with throughput vs baseline."
                resourceType={{ type: 'metrics_pipeline' }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={urls.metricsPipeline('new')}
                        data-attr="new-metrics-pipeline"
                    >
                        New pipeline
                    </LemonButton>
                }
            />
            <LemonTable
                dataSource={pipelines}
                loading={pipelinesLoading}
                rowKey="id"
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        render: (_, pipeline: MetricsPipelineApi) => (
                            <LemonButton to={urls.metricsPipeline(pipeline.id)} size="small">
                                {pipeline.name}
                            </LemonButton>
                        ),
                    },
                    { title: 'Description', dataIndex: 'description' },
                    {
                        title: 'Nodes',
                        render: (_, pipeline: MetricsPipelineApi) => pipeline.config.nodes.length,
                    },
                    {
                        title: 'Created by',
                        render: (_, pipeline: MetricsPipelineApi) => pipeline.created_by?.email ?? '—',
                    },
                    createdAtColumn<MetricsPipelineApi>() as LemonTableColumn<
                        MetricsPipelineApi,
                        keyof MetricsPipelineApi | undefined
                    >,
                    {
                        title: '',
                        render: (_, pipeline: MetricsPipelineApi) => (
                            <LemonButton
                                size="small"
                                status="danger"
                                onClick={() => deletePipeline(pipeline.id)}
                                data-attr="delete-metrics-pipeline"
                            >
                                Delete
                            </LemonButton>
                        ),
                    },
                ]}
                emptyState="No pipelines yet. Create one to map a system's topology onto its metrics."
            />
        </SceneContent>
    )
}
