import { useActions } from 'kea'

import { IconPerson } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import {
    TriggerFrequencyOption,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'

export type PersonUpdatesTriggerConfig = {
    type: 'person-updates'
    filters: {
        properties?: any[]
    }
    include_deleted?: boolean
}

export function isPersonUpdatesTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is PersonUpdatesTriggerConfig {
    return config.type === 'person-updates'
}

const ONCE_PER_PERSON_PER_DAY_HASH = "{concat(toString(person.id), '-', formatDateTime(now(), '%Y-%m-%d'))}"
const CALENDAR_DAY_TTL = 24 * 60 * 60

const personUpdateFrequencyOptions: TriggerFrequencyOption[] = [
    { value: null, label: 'Every time a person changes' },
    { value: '{person.id}', label: 'One time' },
    { value: ONCE_PER_PERSON_PER_DAY_HASH, label: 'Once per calendar day', fixedTtl: CALENDAR_DAY_TTL },
]

function StepTriggerConfigurationPersonUpdates({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)

    const config = node.data.config as PersonUpdatesTriggerConfig
    const properties = config.filters?.properties ?? []

    const updateTriggerConfig = (changes: Partial<PersonUpdatesTriggerConfig>): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'person-updates',
            filters: { properties },
            ...(config.include_deleted ? { include_deleted: true } : {}),
            ...changes,
        })
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs whenever a person's properties change. It runs once per change, so a person can enter
                it repeatedly unless you limit the frequency below.
            </p>

            <LemonField.Pure label="Only trigger for specific people">
                <HogFlowPropertyFilters
                    filtersKey={`person-updates-trigger-${node.data.id}`}
                    filters={{ properties }}
                    setFilters={(filters) =>
                        updateTriggerConfig({ filters: { properties: filters?.properties ?? [] } })
                    }
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ]}
                />
            </LemonField.Pure>

            <LemonSwitch
                bordered
                checked={config.include_deleted === true}
                onChange={(checked) => updateTriggerConfig({ include_deleted: checked })}
                label="Also run when a person is deleted"
                tooltip="Deletions arrive as a person change. Leave this off to skip them."
            />
        </div>
    )
}

registerTriggerType({
    value: 'person-updates',
    label: 'Person updated',
    icon: <IconPerson />,
    description: "Trigger when a person's properties change",
    group: 'Persons and groups',
    featureFlag: 'cdp-person-updates',
    matchConfig: (config) => isPersonUpdatesTriggerConfig(config),
    buildConfig: () => ({
        type: 'person-updates',
        filters: { properties: [] },
    }),
    ConfigComponent: StepTriggerConfigurationPersonUpdates,
    frequencyOptions: personUpdateFrequencyOptions,
    frequencyDescription: 'Limit how often each person can enter this workflow',
})
