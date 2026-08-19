import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { groupsModel } from '~/models/groupsModel'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import {
    TriggerFrequencyOption,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'

export type GroupUpdatesTriggerConfig = {
    type: 'group-updates'
    group_type_index?: number
    filters: {
        properties?: any[]
    }
}

export function isGroupUpdatesTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is GroupUpdatesTriggerConfig {
    return config.type === 'group-updates'
}

// The group key rides in on event.distinct_id, so it keys masking without needing the group type name.
const ONCE_PER_GROUP_PER_DAY_HASH = "{concat(event.distinct_id, '-', formatDateTime(now(), '%Y-%m-%d'))}"
const CALENDAR_DAY_TTL = 24 * 60 * 60

const groupUpdateFrequencyOptions: TriggerFrequencyOption[] = [
    { value: null, label: 'Every time a group changes' },
    { value: '{event.distinct_id}', label: 'One time' },
    { value: ONCE_PER_GROUP_PER_DAY_HASH, label: 'Once per calendar day', fixedTtl: CALENDAR_DAY_TTL },
]

function StepTriggerConfigurationGroupUpdates({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { groupTypes, aggregationLabel } = useValues(groupsModel)

    const config = node.data.config as GroupUpdatesTriggerConfig
    const properties = config.filters?.properties ?? []
    const groupTypeIndex = typeof config.group_type_index === 'number' ? config.group_type_index : null
    const validationResult = actionValidationErrorsById[node.data.id]

    const groupTypeOptions = Array.from(groupTypes.values()).map((groupType) => ({
        label: aggregationLabel(groupType.group_type_index).singular,
        value: groupType.group_type_index as number,
    }))

    const updateTriggerConfig = (index: number | null, newProperties: any[]): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'group-updates',
            ...(index === null ? {} : { group_type_index: index }),
            filters: { properties: newProperties },
        })
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs whenever a group's properties change. Runs are scoped to the group, so there is no
                associated person and person-dependent steps are unavailable.
            </p>

            <LemonField.Pure label="Group type" error={validationResult?.errors?.group_type_index}>
                <LemonSelect
                    options={groupTypeOptions}
                    value={groupTypeIndex}
                    disabledReason={groupTypeOptions.length === 0 ? 'This project has no group types yet' : undefined}
                    onChange={(index) => updateTriggerConfig(index, properties)}
                    placeholder="Select a group type"
                />
                {groupTypeOptions.length === 0 && (
                    <LemonBanner type="warning" className="w-full mt-1">
                        <p className="mb-0">
                            This project doesn't track any groups yet, so this trigger has nothing to listen to. Send a
                            group identify call first, then come back and pick the group type.
                        </p>
                    </LemonBanner>
                )}
            </LemonField.Pure>

            <LemonField.Pure label="Only trigger for specific groups">
                <HogFlowPropertyFilters
                    filtersKey={`group-updates-trigger-${node.data.id}`}
                    filters={{ properties }}
                    setFilters={(filters) => updateTriggerConfig(groupTypeIndex, filters?.properties ?? [])}
                    taxonomicGroupTypes={
                        groupTypeIndex === null
                            ? [TaxonomicFilterGroupType.HogQLExpression]
                            : [
                                  `${TaxonomicFilterGroupType.GroupsPrefix}_${groupTypeIndex}` as TaxonomicFilterGroupType,
                                  TaxonomicFilterGroupType.HogQLExpression,
                              ]
                    }
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'group-updates',
    label: 'Group updated',
    icon: <IconPeople />,
    description: "Trigger when a group's properties change",
    group: 'Persons and groups',
    featureFlag: 'cdp-group-updates',
    matchConfig: (config) => isGroupUpdatesTriggerConfig(config),
    buildConfig: () => ({
        type: 'group-updates',
        filters: { properties: [] },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'group-updates') {
            return null
        }
        if (typeof config.group_type_index !== 'number') {
            return { valid: false, errors: { group_type_index: 'Please select a group type' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationGroupUpdates,
    frequencyOptions: groupUpdateFrequencyOptions,
    frequencyDescription: 'Limit how often each group can enter this workflow',
})
