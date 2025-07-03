import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'
import { getOutgoers, useReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { HogFlowFilters } from './filters/HogFlowFilters'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { getHogFlowStep } from './steps/HogFlowSteps'

export function HogFlowEditorDetailsPanel(): JSX.Element | null {
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
        <div className="flex flex-col flex-1 max-h-full w-120 overflow-y-scroll">
            <div className="flex justify-between items-center px-2 my-2">
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

            <ScrollableShadows direction="vertical" innerClassName="flex flex-col gap-2 p-3" styledScrollbars>
                {Step?.renderConfiguration(selectedNode)}
            </ScrollableShadows>

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
                                Add conditions to the step. If these conditions aren't met, the user will skip this step
                                and continue to the next one.
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
    )
}
