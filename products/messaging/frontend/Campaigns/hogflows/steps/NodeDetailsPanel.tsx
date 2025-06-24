import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'
import { getOutgoers, Panel, useReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { HogFlowFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { getHogFlowStep } from './HogFlowSteps'

export function NodeDetailsPanel(): JSX.Element | null {
    const { selectedNode, nodes, edges } = useValues(hogFlowEditorLogic)
    const { setSelectedNodeId, setCampaignAction } = useActions(hogFlowEditorLogic)

    const { deleteElements } = useReactFlow()

    if (!selectedNode) {
        return null
    }

    const canBeDeleted = (): boolean => {
        const outgoingNodes = getOutgoers(selectedNode, nodes, edges)
        if (outgoingNodes.length === 1) {
            return true
        }

        return new Set(outgoingNodes.map((node) => node.id)).size === 1
    }

    const action = selectedNode.data
    const Step = getHogFlowStep(action.type)

    return (
        <Panel position="top-right" className="bottom">
            <div className="bg-surface-primary border rounded-md shadow-lg flex flex-col z-10 min-w-[300px] max-w-[500px] max-h-full">
                <div className="flex justify-between items-center p-2">
                    <h3 className="flex gap-1 items-center mb-0 font-semibold">
                        <span className="text-lg">{Step?.icon}</span> Edit {selectedNode.data.name} step
                    </h3>
                    <div className="flex gap-1 items-center">
                        {selectedNode.deletable && (
                            <LemonButton
                                size="xsmall"
                                status="danger"
                                onClick={() => {
                                    void deleteElements({ nodes: [selectedNode] })
                                    setSelectedNodeId(null)
                                }}
                                icon={<IconTrash />}
                                disabledReason={canBeDeleted() ? undefined : 'Clean up branching steps first'}
                            />
                        )}
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={() => setSelectedNodeId(null)}
                            aria-label="close"
                        />
                    </div>
                </div>
                <LemonDivider className="my-0" />
                <div className="flex overflow-y-auto flex-col gap-2 p-2">{Step?.renderConfiguration(selectedNode)}</div>

                <LemonDivider className="my-0" />
                {!['trigger', 'exit'].includes(action.type) && (
                    <div className="flex flex-col p-2">
                        <LemonLabel htmlFor="conditions" className="flex gap-2 justify-between items-center">
                            <span>Conditions</span>
                            <LemonSwitch
                                id="conditions"
                                checked={!!action.filters}
                                onChange={(checked) =>
                                    setCampaignAction(action.id, {
                                        ...action,
                                        filters: checked ? {} : null,
                                    })
                                }
                            />
                        </LemonLabel>

                        {action.filters && (
                            <>
                                <p className="mb-0">
                                    Add conditions to the step. If these conditions aren't met, the user will skip this
                                    step and continue to the next one.
                                </p>
                                <HogFlowFilters
                                    filters={action.filters ?? {}}
                                    setFilters={(filters) => setCampaignAction(action.id, { ...action, filters })}
                                    buttonCopy="Add filter conditions"
                                />
                            </>
                        )}
                    </div>
                )}
            </div>
        </Panel>
    )
}
