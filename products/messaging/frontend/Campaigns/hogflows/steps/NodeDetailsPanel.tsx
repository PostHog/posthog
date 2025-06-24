import { IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel } from '@posthog/lemon-ui'
import { getOutgoers, Panel, useReactFlow } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

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

    // TODO: Add default "conditions" for filtering people out

    const action = selectedNode.data
    const Step = getHogFlowStep(action.type)

    return (
        <Panel position="top-right" className="bottom">
            <div className="bg-surface-primary rounded-md shadow-md flex flex-col z-10 min-w-[300px] max-w-[500px] max-h-full">
                <div className="flex justify-between items-center p-2">
                    <h3 className="mb-0 font-semibold">Edit {selectedNode.data.name} step</h3>
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

                <LemonDivider className="my-0" />
                {!['trigger', 'exit'].includes(action.type) && (
                    <div className="flex flex-col gap-2 p-2">
                        <LemonLabel>Conditions</LemonLabel>

                        <ActionFilter
                            filters={action.filters ?? {}}
                            setFilters={(filters) => setCampaignAction(action.id, { ...action, filters })}
                            typeKey="action-filter"
                            mathAvailability={MathAvailability.None}
                            hideRename
                            hideDuplicate
                            showNestedArrow={false}
                            actionsTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.Events,
                                TaxonomicFilterGroupType.Actions,
                            ]}
                            propertiesTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.EventFeatureFlags,
                                TaxonomicFilterGroupType.Elements,
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                            propertyFiltersPopover
                            buttonProps={{
                                type: 'secondary',
                            }}
                            buttonCopy="Add filter conditions"
                        />
                    </div>
                )}
            </div>
        </Panel>
    )
}
