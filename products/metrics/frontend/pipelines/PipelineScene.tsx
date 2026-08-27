import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect, LemonTag, Spinner } from '@posthog/lemon-ui'

import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { PipelineDrillPanel } from './PipelineDrillPanel'
import { PipelineEditor } from './PipelineEditor'
import { PipelineGraph } from './PipelineGraph'
import { NEW_PIPELINE_ID, PipelineLogicProps, pipelineLogic } from './pipelineLogic'

export const scene: SceneExport<PipelineLogicProps> = {
    component: MetricsPipelineScene,
    logic: pipelineLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? NEW_PIPELINE_ID }),
    productKey: ProductKey.METRICS,
}

export function MetricsPipelineScene({ id }: PipelineLogicProps = { id: NEW_PIPELINE_ID }): JSX.Element {
    const logic = pipelineLogic({ id })
    const {
        pipeline,
        pipelineLoading,
        evaluation,
        evaluationLoading,
        config,
        selectedNodeId,
        selectedEdgeKey,
        variableValues,
        autoRefreshEnabled,
        editing,
        draft,
        isNew,
        lastRefreshedAt,
    } = useValues(logic)
    const {
        selectNode,
        selectEdge,
        setVariableValue,
        setAutoRefresh,
        startEditing,
        cancelEditing,
        savePipeline,
        evaluate,
    } = useActions(logic)

    if (pipelineLoading && !pipeline && !isNew) {
        return (
            <div className="flex items-center justify-center h-60">
                <Spinner />
            </div>
        )
    }

    const showEditor = editing || isNew

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New pipeline' : (pipeline?.name ?? 'Pipeline')}
                description={pipeline?.description}
                resourceType={{ type: 'metrics_pipeline' }}
                actions={
                    showEditor ? (
                        <div className="flex gap-2">
                            {!isNew && (
                                <LemonButton type="secondary" onClick={cancelEditing} data-attr="pipeline-cancel-edit">
                                    Cancel
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                onClick={savePipeline}
                                disabledReason={
                                    !draft?.name
                                        ? 'Give the pipeline a name'
                                        : !draft?.config.nodes.length
                                          ? 'Add at least one node'
                                          : undefined
                                }
                                data-attr="pipeline-save"
                            >
                                {isNew ? 'Create pipeline' : 'Save'}
                            </LemonButton>
                        </div>
                    ) : (
                        <div className="flex gap-2">
                            <LemonButton type="secondary" onClick={startEditing} data-attr="pipeline-edit-topology">
                                Edit topology
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => evaluate(null)}
                                loading={evaluationLoading}
                                data-attr="pipeline-refresh"
                            >
                                Refresh
                            </LemonButton>
                        </div>
                    )
                }
            />

            {showEditor ? (
                <PipelineEditor id={id} />
            ) : (
                <>
                    <div className="flex items-center gap-2 flex-wrap">
                        {(config.variables ?? []).map((variable) => (
                            <LemonSelect
                                key={variable.key}
                                size="small"
                                placeholder={variable.label}
                                value={variableValues[variable.key] ?? variable.default ?? null}
                                onChange={(value) => setVariableValue(variable.key, value)}
                                options={(variable.options ?? []).map((option) => ({ value: option, label: option }))}
                                allowClear
                            />
                        ))}
                        <div className="flex-1" />
                        <LemonSwitch
                            checked={autoRefreshEnabled}
                            onChange={setAutoRefresh}
                            label="Auto-refresh"
                            bordered
                            size="small"
                        />
                        {lastRefreshedAt ? (
                            <span className="text-xs text-muted font-mono">
                                updated {new Date(lastRefreshedAt).toLocaleTimeString()}
                            </span>
                        ) : null}
                    </div>

                    {evaluation?.alerts.length ? (
                        <LemonBanner
                            type={evaluation.alerts.some((a) => a.severity === 'critical') ? 'error' : 'warning'}
                        >
                            <div className="flex flex-col gap-1">
                                {evaluation.alerts.map((alert) => (
                                    <div key={`${alert.node_id}-${alert.stat_id}`} className="flex items-center gap-2">
                                        <LemonTag type={alert.severity === 'critical' ? 'danger' : 'warning'}>
                                            {alert.severity}
                                        </LemonTag>
                                        <span className="text-sm">{alert.message}</span>
                                        <LemonButton size="xsmall" onClick={() => selectNode(alert.node_id)}>
                                            investigate
                                        </LemonButton>
                                    </div>
                                ))}
                            </div>
                        </LemonBanner>
                    ) : null}

                    <div className="border rounded bg-surface-primary" style={{ height: 420 }}>
                        <PipelineGraph
                            config={config}
                            evaluation={evaluation}
                            selectedNodeId={selectedNodeId}
                            selectedEdgeKey={selectedEdgeKey}
                            onSelectNode={selectNode}
                            onSelectEdge={selectEdge}
                        />
                    </div>

                    <PipelineDrillPanel
                        config={config}
                        evaluation={evaluation}
                        selectedNodeId={selectedNodeId}
                        selectedEdgeKey={selectedEdgeKey}
                    />
                </>
            )}
        </SceneContent>
    )
}
