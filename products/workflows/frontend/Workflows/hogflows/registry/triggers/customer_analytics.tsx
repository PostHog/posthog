import { useActions, useValues } from 'kea'

import { IconBolt, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonInputSelect } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { tagsModel } from '~/models/tagsModel'

import { accountCustomPropertyDefinitionsLogic } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/accountCustomPropertyDefinitionsLogic'
import {
    type EventTriggerConfig,
    type TriggerFrequencyOption,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

const ACCOUNT_TAG_ADDED_EVENT = '$account_tag_added'
const ACCOUNT_CUSTOM_PROPERTY_CHANGED_EVENT = '$account_custom_property_changed'

function getEventId(config: EventTriggerConfig): string | null {
    const [firstEvent] = config.filters?.events ?? []
    return typeof firstEvent?.id === 'string' ? firstEvent.id : null
}

export function getSelectedTags(config: EventTriggerConfig): string[] {
    const tagProperty = (config.filters?.properties ?? []).find((property: any) => property?.key === 'tag')
    if (!tagProperty) {
        return []
    }
    const values = Array.isArray(tagProperty.value) ? tagProperty.value : [tagProperty.value]
    return values.filter((tag: unknown): tag is string => typeof tag === 'string')
}

export function accountTagAddedFilters(tags: string[]): EventTriggerConfig['filters'] {
    return {
        events: [{ id: ACCOUNT_TAG_ADDED_EVENT, type: 'events', name: 'Account tag added' }],
        properties: tags.length > 0 ? [{ key: 'tag', value: tags, operator: 'exact', type: 'event' }] : [],
    }
}

function StepTriggerConfigurationAccountTagAdded({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { tags, tagsLoading } = useValues(tagsModel)
    const config = node.data.config as EventTriggerConfig
    const selectedTags = getSelectedTags(config)

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when a tag is added to an account. Leave empty to run for any tag.
            </p>
            <LemonField.Pure label="Tags">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={selectedTags}
                    loading={tagsLoading}
                    placeholder="Any tag"
                    options={tags.map((tag: string) => ({ key: tag, label: tag }))}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: accountTagAddedFilters(value),
                        })
                    }
                    data-attr="account-tag-added-trigger-tags"
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'account_tag_added',
    label: 'Account tag added',
    icon: <IconBolt />,
    description: 'Trigger when a tag is added to an account',
    group: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === ACCOUNT_TAG_ADDED_EVENT,
    buildConfig: () => ({
        type: 'event',
        filters: accountTagAddedFilters([]),
    }),
    ConfigComponent: StepTriggerConfigurationAccountTagAdded,
})

// Account events carry no person (they use a synthetic distinct_id), so the generic person-keyed
// frequency hashes would resolve empty and mask globally — key on the event's account instead.
const ONCE_PER_ACCOUNT_PROPERTY_HASH = "{concat(event.properties.account_id, '-', event.properties.property_name)}"
const ONCE_PER_ACCOUNT_PROPERTY_PER_DAY_HASH =
    "{concat(event.properties.account_id, '-', event.properties.property_name, '-', formatDateTime(now(), '%Y-%m-%d'))}"
const CALENDAR_DAY_TTL = 24 * 60 * 60

export const accountCustomPropertyFrequencyOptions: TriggerFrequencyOption[] = [
    { value: null, label: 'Every time the trigger fires' },
    { value: ONCE_PER_ACCOUNT_PROPERTY_HASH, label: 'Once per account and property' },
    {
        value: ONCE_PER_ACCOUNT_PROPERTY_PER_DAY_HASH,
        label: 'Once per account and property per calendar day',
        fixedTtl: CALENDAR_DAY_TTL,
    },
]

export function getSelectedPropertyNames(config: EventTriggerConfig): string[] {
    const nameProperty = (config.filters?.properties ?? []).find((property: any) => property?.key === 'property_name')
    if (!nameProperty) {
        return []
    }
    const values = Array.isArray(nameProperty.value) ? nameProperty.value : [nameProperty.value]
    return values.filter((name: unknown): name is string => typeof name === 'string')
}

export function accountCustomPropertyChangedFilters(names: string[]): EventTriggerConfig['filters'] {
    return {
        events: [
            { id: ACCOUNT_CUSTOM_PROPERTY_CHANGED_EVENT, type: 'events', name: 'Account custom property changed' },
        ],
        properties: names.length > 0 ? [{ key: 'property_name', value: names, operator: 'exact', type: 'event' }] : [],
    }
}

const TRIGGER_EVENT_TEMPLATES = [
    '{event.properties.property_name}',
    '{event.properties.previous_value}',
    '{event.properties.current_value}',
]

function StepTriggerConfigurationAccountCustomPropertyChanged({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { accountPropertyNames, definitionsLoading } = useValues(accountCustomPropertyDefinitionsLogic)
    const config = node.data.config as EventTriggerConfig
    const selectedNames = getSelectedPropertyNames(config)

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when an account custom property value changes. Leave empty to run for any property.
            </p>
            <LemonField.Pure label="Properties">
                <LemonInputSelect
                    mode="multiple"
                    value={selectedNames}
                    loading={definitionsLoading}
                    placeholder="Any property"
                    options={accountPropertyNames.map((name: string) => ({ key: name, label: name }))}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: accountCustomPropertyChangedFilters(value),
                        })
                    }
                    data-attr="account-custom-property-changed-trigger-properties"
                />
            </LemonField.Pure>
            {selectedNames.length !== 1 && (
                <LemonBanner type="info">
                    The workflow starts once per changed property. If two matching properties change at the same time,
                    two separate runs start.
                </LemonBanner>
            )}
            <LemonField.Pure label="Available in steps" help="Reference the change from any step, filter, or condition">
                <div className="flex flex-col gap-1">
                    {TRIGGER_EVENT_TEMPLATES.map((template) => (
                        <CodeSnippet key={template} compact thing="template">
                            {template}
                        </CodeSnippet>
                    ))}
                </div>
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'account_custom_property_changed',
    label: 'Account property changed',
    icon: <IconPencil />,
    description: 'Trigger when an account custom property value changes',
    group: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === ACCOUNT_CUSTOM_PROPERTY_CHANGED_EVENT,
    buildConfig: () => ({
        type: 'event',
        filters: accountCustomPropertyChangedFilters([]),
    }),
    ConfigComponent: StepTriggerConfigurationAccountCustomPropertyChanged,
    frequencyOptions: accountCustomPropertyFrequencyOptions,
    frequencyDescription: 'Limit how often each account can enter this workflow',
})
