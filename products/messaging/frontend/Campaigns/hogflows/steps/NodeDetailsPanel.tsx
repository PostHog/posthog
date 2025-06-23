import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { Panel } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { getHogFlowStep } from './HogFlowSteps'

export function NodeDetailsPanel(): JSX.Element | null {
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const { setSelectedNode } = useActions(hogFlowEditorLogic)

    if (!selectedNode) {
        return null
    }

    // // eslint-disable-next-line react-hooks/exhaustive-deps
    // const hogFlowAction = useMemo(() => HogFlowActionManager.fromReactFlowNode(node), [node.data])

    // const canBeDeleted = (): boolean => {
    //     const outgoingNodes = getOutgoers(node, nodes, edges)
    //     if (outgoingNodes.length === 1) {
    //         return true
    //     }

    //     return new Set(outgoingNodes.map((node) => node.id)).size === 1
    // }

    // const handleInputChange = (key: string, value: any): void => {
    //     hogFlowAction.setInput(key, value)
    //     onChange(hogFlowAction.toReactFlowNode())
    // }

    const Step = getHogFlowStep(selectedNode.data.type)

    return (
        <Panel position="top-right">
            <div className="bg-surface-primary rounded-md shadow-md flex flex-col z-10 min-w-[300px] max-w-[500px] max-h-3/4">
                <div className="flex justify-between items-center p-2">
                    <h3 className="mb-0 font-semibold">Edit {selectedNode.data.name} step</h3>
                    <div className="flex gap-1 items-center">
                        {selectedNode.deletable && (
                            <LemonButton
                                size="xsmall"
                                status="danger"
                                onClick={() => alert('not implemented')}
                                icon={<IconTrash />}
                                // disabledReason={canBeDeleted() ? undefined : 'Clean up branching steps first'}
                            />
                        )}
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={() => setSelectedNode(null)}
                            aria-label="close"
                        />
                    </div>
                </div>
                <LemonDivider className="my-0" />
                <div className="flex overflow-y-auto flex-col gap-2 p-2">
                    {Step?.renderConfiguration(selectedNode)}
                    {/* {hogFlowAction instanceof TriggerAction ? (
                        <TriggerPanelOptions action={hogFlowAction} />
                    ) : (
                        <p>TODO</p>
                        // <CyclotronJobInputs
                        //     configuration={{
                        //         inputs: hogFlowAction.getInputs(),
                        //         inputs_schema: hogFlowAction.getInputsSchema(),
                        //     }}
                        //     onInputChange={handleInputChange}
                        //     showSource={false}
                        // />
                    )} */}
                </div>
            </div>
        </Panel>
    )
}
