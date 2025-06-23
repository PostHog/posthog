import { IconBolt } from '@posthog/icons'
import { Node, Position } from '@xyflow/react'
import { useActions } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { BOTTOM_HANDLE_POSITION } from '../constants'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepTrigger: HogFlowStep<'trigger'> = {
    type: 'trigger',
    renderNode: (props) => <StepTriggerNode {...props} />,
    renderConfiguration: (node) => <StepTriggerConfiguration node={node} />,
    create: (edgeToInsertNodeInto) => {
        return {
            name: 'Trigger',
            description: '',
            type: 'trigger',
            config: {
                type: 'event',
            },
        }
    },
    getHandles(action) {
        return [
            {
                id: `continue_${action.id}`,
                type: 'source',
                position: Position.Bottom,
                ...BOTTOM_HANDLE_POSITION,
            },
        ]
    },
}

function StepTriggerNode({ data }: HogFlowStepNodeProps): JSX.Element {
    // TODO: Use node data to render trigger node
    return (
        <StepView
            name={data.name}
            icon={<IconBolt className="text-green-400" />}
            selected={false}
            handles={StepTrigger.getHandles(data)}
        />
    )
}

function StepTriggerConfiguration({ node }: { node: Node<Extract<HogFlowAction, { type: 'trigger' }>> }): JSX.Element {
    const action = node.data
    const { filters } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Campaign trigger event</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
            <ActionFilter
                filters={filters ?? {}}
                setFilters={(filters) => setCampaignActionConfig(action.id, { filters })}
                typeKey="campaign-trigger"
                mathAvailability={MathAvailability.None}
                hideRename
                hideDuplicate
                showNestedArrow={false}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
                propertyFiltersPopover
                addFilterDefaultOptions={{
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                }}
                buttonProps={{
                    type: 'secondary',
                }}
                buttonCopy="Add trigger event"
            />
        </>
    )
}
