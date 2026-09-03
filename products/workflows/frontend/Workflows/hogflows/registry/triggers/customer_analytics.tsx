import { useActions, useValues } from 'kea'

import { IconBolt, IconPencil, IconPerson, IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { tagsModel } from '~/models/tagsModel'
import { PropertyDefinition, PropertyDefinitionType, PropertyType } from '~/types'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'
import { HogFlowPropertyFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters'
import { accountCustomPropertyDefinitionsLogic } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/accountCustomPropertyDefinitionsLogic'
import { accountRelationshipDefinitionsLogic } from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/accountRelationshipDefinitionsLogic'
import {
    type EventTriggerConfig,
    type TriggerFrequencyOption,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

const ACCOUNT_TAG_ADDED_EVENT = '$account_tag_added'
const ACCOUNT_TAG_REMOVED_EVENT = '$account_tag_removed'
const ACCOUNT_CUSTOM_PROPERTY_CHANGED_EVENT = '$account_custom_property_changed'
const ACCOUNT_RELATIONSHIP_CHANGED_EVENT = '$account_relationship_changed'

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

const ACCOUNT_TAG_CHANGE_TYPES = ['added', 'removed'] as const
export type AccountTagChangeType = (typeof ACCOUNT_TAG_CHANGE_TYPES)[number]

export function getAccountTagChangeType(config: EventTriggerConfig): AccountTagChangeType | null {
    const eventIds = (config.filters?.events ?? []).map((event: any) => event?.id)
    const includesAdded = eventIds.includes(ACCOUNT_TAG_ADDED_EVENT)
    const includesRemoved = eventIds.includes(ACCOUNT_TAG_REMOVED_EVENT)

    if (includesAdded === includesRemoved) {
        return null
    }
    return includesAdded ? 'added' : 'removed'
}

const accountTagChangedEvent = (changeType: AccountTagChangeType): any => ({
    id: changeType === 'added' ? ACCOUNT_TAG_ADDED_EVENT : ACCOUNT_TAG_REMOVED_EVENT,
    type: 'events',
    name: changeType === 'added' ? 'Account tag added' : 'Account tag removed',
})

export function accountTagChangedFilters(
    tags: string[],
    existingFilters: EventTriggerConfig['filters'] = {},
    changeType: AccountTagChangeType | null = getAccountTagChangeType({ type: 'event', filters: existingFilters })
): EventTriggerConfig['filters'] {
    const changeTypes: AccountTagChangeType[] = changeType ? [changeType] : ['added', 'removed']

    return {
        ...existingFilters,
        events: changeTypes.map(accountTagChangedEvent),
        properties: [
            ...(tags.length > 0 ? [{ key: 'tag', value: tags, operator: 'exact', type: 'event' }] : []),
            ...(existingFilters.properties ?? []).filter((property: any) => property?.key !== 'tag'),
        ],
    }
}

function isAccountTagChangedConfig(config: EventTriggerConfig): boolean {
    if (config.type !== 'event') {
        return false
    }
    const events = config.filters?.events ?? []
    return (
        events.length > 0 &&
        events.every(
            (event: any) =>
                (event?.id === ACCOUNT_TAG_ADDED_EVENT || event?.id === ACCOUNT_TAG_REMOVED_EVENT) &&
                !event?.properties?.length
        )
    )
}

function StepTriggerConfigurationAccountTagChanged({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { tags, tagsLoading } = useValues(tagsModel)
    const config = node.data.config as EventTriggerConfig
    const selectedTags = getSelectedTags(config)
    const changeType = getAccountTagChangeType(config)

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when a tag is added to or removed from an account. Leave empty to run for any tag.
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
                            filters: accountTagChangedFilters(value, config.filters),
                        })
                    }
                    data-attr="account-tag-added-trigger-tags"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Change type" info="Limit this trigger to tags that were added or removed.">
                <LemonSelect<AccountTagChangeType | null>
                    value={changeType}
                    placeholder="Any change type"
                    allowClear
                    options={[
                        { label: 'Added', value: 'added' },
                        { label: 'Removed', value: 'removed' },
                    ]}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: accountTagChangedFilters(selectedTags, config.filters, value),
                        })
                    }
                    data-attr="account-tag-change-type-filter"
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'account_tag_changed',
    label: 'Account tag changed',
    icon: <IconBolt />,
    description: 'Trigger when a tag is added to or removed from an account',
    group: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    matchConfig: isAccountTagChangedConfig,
    buildConfig: () => ({
        type: 'event',
        filters: accountTagChangedFilters([]),
    }),
    ConfigComponent: StepTriggerConfigurationAccountTagChanged,
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

export type AccountCustomPropertyChangedCondition = {
    propertyName: string
    valueFilters: any[]
}

function propertyValues(property: any): string[] {
    const values = Array.isArray(property?.value) ? property.value : [property?.value]
    return values.filter((name: unknown): name is string => typeof name === 'string')
}

function topLevelPropertyNames(config: EventTriggerConfig): string[] {
    const property = (config.filters?.properties ?? []).find((candidate: any) => candidate?.key === 'property_name')
    return propertyValues(property)
}

/**
 * Each event filter is one OR branch. Its nested properties stay ANDed, giving us:
 * (property_name = Plan AND current_value = enterprise) OR
 * (property_name = Seats AND current_value > 5).
 *
 * Older/MCP configs use top-level properties. Distribute those filters across the selected
 * property names so the first UI edit upgrades the config without changing its meaning.
 */
export function getAccountCustomPropertyChangedConditions(
    config: EventTriggerConfig
): AccountCustomPropertyChangedCondition[] {
    const topLevelValueFilters = (config.filters?.properties ?? []).filter(
        (property: any) => property?.key !== 'property_name'
    )
    const groupedConditions = (config.filters?.events ?? []).flatMap((event: any) => {
        if (event?.id !== ACCOUNT_CUSTOM_PROPERTY_CHANGED_EVENT) {
            return []
        }
        const properties = event.properties ?? []
        const nameProperty = properties.find((property: any) => property?.key === 'property_name')
        return propertyValues(nameProperty).map((propertyName) => ({
            propertyName,
            valueFilters: [
                ...properties.filter((property: any) => property?.key !== 'property_name'),
                ...topLevelValueFilters,
            ],
        }))
    })

    if (groupedConditions.length > 0) {
        return groupedConditions.filter(
            (condition, index) =>
                groupedConditions.findIndex((candidate) => candidate.propertyName === condition.propertyName) === index
        )
    }

    return topLevelPropertyNames(config).map((propertyName) => ({
        propertyName,
        valueFilters: topLevelValueFilters,
    }))
}

export function getSelectedPropertyNames(config: EventTriggerConfig): string[] {
    const groupedNames = getAccountCustomPropertyChangedConditions(config).map((condition) => condition.propertyName)
    return groupedNames.length > 0 ? groupedNames : topLevelPropertyNames(config)
}

export function getAccountCustomPropertyValueFilters(config: EventTriggerConfig): any[] {
    return getAccountCustomPropertyChangedConditions(config).flatMap((condition) => condition.valueFilters)
}

const accountCustomPropertyChangedEvent = (properties: any[] = []): any => ({
    id: ACCOUNT_CUSTOM_PROPERTY_CHANGED_EVENT,
    type: 'events',
    name: 'Account custom property changed',
    ...(properties.length > 0 ? { properties } : {}),
})

export function accountCustomPropertyChangedFilters(
    names: string[],
    existingFilters: EventTriggerConfig['filters'] = {},
    conditions: AccountCustomPropertyChangedCondition[] = getAccountCustomPropertyChangedConditions({
        type: 'event',
        filters: existingFilters,
    })
): EventTriggerConfig['filters'] {
    const conditionsByName = new Map(conditions.map((condition) => [condition.propertyName, condition]))
    const selectedConditions = names.map(
        (propertyName): AccountCustomPropertyChangedCondition =>
            conditionsByName.get(propertyName) ?? { propertyName, valueFilters: [] }
    )

    return {
        ...existingFilters,
        events:
            selectedConditions.length > 0
                ? selectedConditions.map((condition) =>
                      accountCustomPropertyChangedEvent([
                          {
                              key: 'property_name',
                              value: condition.propertyName,
                              operator: 'exact',
                              type: 'event',
                          },
                          ...condition.valueFilters,
                      ])
                  )
                : [accountCustomPropertyChangedEvent()],
        // Conditions are nested under each event filter. Keeping them top-level would AND them
        // with every OR branch and recreate the ambiguity this trigger-specific editor avoids.
        properties:
            selectedConditions.length > 0
                ? []
                : (existingFilters.properties ?? []).filter((property: any) => property?.key !== 'property_name'),
    }
}

export function customPropertyDisplayTypeToPropertyType(
    displayType: CustomPropertyDefinitionApi['display_type'] | undefined
): PropertyType {
    switch (displayType) {
        case 'number':
        case 'currency':
        case 'percent':
            return PropertyType.Numeric
        case 'boolean':
            return PropertyType.Boolean
        case 'date':
        case 'datetime':
            return PropertyType.DateTime
        default:
            return PropertyType.String
    }
}

function currentValuePropertyDefinition(definition: CustomPropertyDefinitionApi | undefined): PropertyDefinition[] {
    return [
        {
            id: `account-custom-property-current-value-${definition?.id ?? 'unknown'}`,
            name: 'current_value',
            type: PropertyDefinitionType.Event,
            property_type: customPropertyDisplayTypeToPropertyType(definition?.display_type),
        },
    ]
}

const TRIGGER_EVENT_TEMPLATES = [
    '{event.properties.property_name}',
    '{event.properties.previous_value}',
    '{event.properties.current_value}',
    '{event.properties.account_external_id}',
    '{event.properties.account_name}',
]

function StepTriggerConfigurationAccountCustomPropertyChanged({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { accountPropertyNames, definitions, definitionsLoading } = useValues(accountCustomPropertyDefinitionsLogic)
    const config = node.data.config as EventTriggerConfig
    const selectedNames = getSelectedPropertyNames(config)
    const conditions = getAccountCustomPropertyChangedConditions(config)

    const updateTriggerConfig = (names: string[], nextConditions: AccountCustomPropertyChangedCondition[]): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'event',
            filters: accountCustomPropertyChangedFilters(names, config.filters, nextConditions),
        })
    }

    const selectProperties = (names: string[]): void => {
        const conditionsByName = new Map(conditions.map((condition) => [condition.propertyName, condition]))
        updateTriggerConfig(
            names,
            names.map((propertyName) => conditionsByName.get(propertyName) ?? { propertyName, valueFilters: [] })
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when an account custom property value changes. Leave empty to run for any property.
            </p>
            <LemonField.Pure
                label="Properties"
                info="Select a property to add a current value condition. With no selection, this trigger runs for any changed property."
            >
                <LemonInputSelect
                    mode="multiple"
                    value={selectedNames}
                    loading={definitionsLoading}
                    placeholder="Any property"
                    options={accountPropertyNames.map((name: string) => ({ key: name, label: name }))}
                    onChange={selectProperties}
                    data-attr="account-custom-property-changed-trigger-properties"
                />
            </LemonField.Pure>
            {conditions.length > 0 ? (
                <LemonField.Pure
                    label="Current value conditions"
                    info="Conditions inside a property group are ANDed. Property groups are ORed."
                >
                    <div className="flex flex-col gap-2">
                        {conditions.map((condition, index) => {
                            const definition = definitions.find(
                                (candidate) =>
                                    candidate.name === condition.propertyName &&
                                    (candidate.target_type ?? 'account') === 'account'
                            )
                            const selectOptions =
                                definition?.display_type === 'select'
                                    ? (definition.options ?? []).map((option) => ({ name: option.label }))
                                    : []

                            return (
                                <div key={condition.propertyName}>
                                    {index > 0 && (
                                        <div className="flex items-center gap-2 my-2 text-xs font-semibold text-muted uppercase">
                                            <div className="flex-1 border-t" />
                                            or
                                            <div className="flex-1 border-t" />
                                        </div>
                                    )}
                                    <div className="relative rounded border bg-surface-primary p-3 flex flex-col gap-2">
                                        <div className="text-sm pr-8">
                                            When <strong>{condition.propertyName}</strong> changes
                                        </div>
                                        {condition.valueFilters.length > 0 && (
                                            <LemonButton
                                                icon={<IconX />}
                                                type="tertiary"
                                                size="xsmall"
                                                noPadding
                                                className="absolute top-3 right-3"
                                                tooltip="Remove value filter"
                                                onClick={() =>
                                                    updateTriggerConfig(
                                                        selectedNames,
                                                        conditions.map((candidate) =>
                                                            candidate.propertyName === condition.propertyName
                                                                ? { ...candidate, valueFilters: [] }
                                                                : candidate
                                                        )
                                                    )
                                                }
                                            />
                                        )}
                                        {condition.valueFilters.length === 0 ? (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                icon={<IconPlusSmall />}
                                                onClick={() =>
                                                    updateTriggerConfig(
                                                        selectedNames,
                                                        conditions.map((candidate) =>
                                                            candidate.propertyName === condition.propertyName
                                                                ? {
                                                                      ...candidate,
                                                                      valueFilters: [
                                                                          {
                                                                              key: 'current_value',
                                                                              value: null,
                                                                              operator: 'exact',
                                                                              type: 'event',
                                                                          },
                                                                      ],
                                                                  }
                                                                : candidate
                                                        )
                                                    )
                                                }
                                                data-attr={`account-custom-property-add-value-filter-${condition.propertyName}`}
                                            >
                                                Add value filter
                                            </LemonButton>
                                        ) : (
                                            <HogFlowPropertyFilters
                                                filtersKey={`account-custom-property-changed-trigger-${node.data.id}-${condition.propertyName}`}
                                                filters={{ properties: condition.valueFilters }}
                                                setFilters={(filters) =>
                                                    updateTriggerConfig(
                                                        selectedNames,
                                                        conditions.map((candidate) =>
                                                            candidate.propertyName === condition.propertyName
                                                                ? {
                                                                      ...candidate,
                                                                      valueFilters: filters?.properties ?? [],
                                                                  }
                                                                : candidate
                                                        )
                                                    )
                                                }
                                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                                propertyAllowList={{
                                                    [TaxonomicFilterGroupType.EventProperties]: ['current_value'],
                                                }}
                                                propertyDefinitionsOverride={currentValuePropertyDefinition(definition)}
                                                staticValueOptions={(propertyKey) =>
                                                    propertyKey === 'current_value' ? selectOptions : null
                                                }
                                                inline
                                                allowNew={false}
                                                propertyKeyEditable={false}
                                                singleLine
                                                showRemoveButton={false}
                                                hasRowOperator={false}
                                            />
                                        )}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </LemonField.Pure>
            ) : null}
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

const ONCE_PER_ACCOUNT_RELATIONSHIP_HASH =
    "{concat(event.properties.account_id, '-', event.properties.relationship_name)}"
const ONCE_PER_ACCOUNT_RELATIONSHIP_PER_DAY_HASH =
    "{concat(event.properties.account_id, '-', event.properties.relationship_name, '-', formatDateTime(now(), '%Y-%m-%d'))}"

export const accountRelationshipFrequencyOptions: TriggerFrequencyOption[] = [
    { value: null, label: 'Every time the trigger fires' },
    { value: ONCE_PER_ACCOUNT_RELATIONSHIP_HASH, label: 'Once per account and relationship' },
    {
        value: ONCE_PER_ACCOUNT_RELATIONSHIP_PER_DAY_HASH,
        label: 'Once per account and relationship per calendar day',
        fixedTtl: CALENDAR_DAY_TTL,
    },
]

export function getSelectedRelationshipNames(config: EventTriggerConfig): string[] {
    const nameProperty = (config.filters?.properties ?? []).find(
        (property: any) => property?.key === 'relationship_name'
    )
    if (!nameProperty) {
        return []
    }
    const values = Array.isArray(nameProperty.value) ? nameProperty.value : [nameProperty.value]
    return values.filter((name: unknown): name is string => typeof name === 'string')
}

const RELATIONSHIP_CHANGE_TYPES = ['assigned', 'unassigned'] as const
export type AccountRelationshipChangeType = (typeof RELATIONSHIP_CHANGE_TYPES)[number]

function isAccountRelationshipChangeType(value: unknown): value is AccountRelationshipChangeType {
    return typeof value === 'string' && RELATIONSHIP_CHANGE_TYPES.includes(value as AccountRelationshipChangeType)
}

export function getAccountRelationshipChangeType(config: EventTriggerConfig): AccountRelationshipChangeType | null {
    const property = (config.filters?.properties ?? []).find((candidate: any) => candidate?.key === 'change_type')
    const value = Array.isArray(property?.value) ? property.value[0] : property?.value
    return isAccountRelationshipChangeType(value) ? value : null
}

export function accountRelationshipChangedFilters(
    names: string[],
    existingFilters: EventTriggerConfig['filters'] = {},
    changeType: AccountRelationshipChangeType | null = getAccountRelationshipChangeType({
        type: 'event',
        filters: existingFilters,
    })
): EventTriggerConfig['filters'] {
    return {
        ...existingFilters,
        events: [{ id: ACCOUNT_RELATIONSHIP_CHANGED_EVENT, type: 'events', name: 'Account relationship changed' }],
        properties: [
            ...(names.length > 0 ? [{ key: 'relationship_name', value: names, operator: 'exact', type: 'event' }] : []),
            ...(changeType ? [{ key: 'change_type', value: changeType, operator: 'exact', type: 'event' }] : []),
        ],
    }
}

const RELATIONSHIP_TRIGGER_EVENT_TEMPLATES = [
    '{event.properties.relationship_name}',
    '{event.properties.change_type}',
    '{event.properties.previous_user_id}',
    '{event.properties.previous_user_email}',
    '{event.properties.current_user_id}',
    '{event.properties.current_user_email}',
    '{event.properties.account_external_id}',
    '{event.properties.account_name}',
]

function StepTriggerConfigurationAccountRelationshipChanged({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { definitions, definitionsLoading } = useValues(accountRelationshipDefinitionsLogic)
    const config = node.data.config as EventTriggerConfig
    const selectedNames = getSelectedRelationshipNames(config)
    const changeType = getAccountRelationshipChangeType(config)

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This trigger runs when an account relationship is assigned or unassigned. Leave empty to run for any
                relationship.
            </p>
            <LemonField.Pure label="Relationships">
                <LemonInputSelect
                    mode="multiple"
                    value={selectedNames}
                    loading={definitionsLoading}
                    placeholder="Any relationship"
                    options={definitions.map((definition) => ({ key: definition.name, label: definition.name }))}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: accountRelationshipChangedFilters(value, config.filters),
                        })
                    }
                    data-attr="account-relationship-changed-trigger-relationships"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Change type"
                info="Limit this trigger to relationships that were assigned or unassigned."
            >
                <LemonSelect<AccountRelationshipChangeType | null>
                    value={changeType}
                    placeholder="Any change type"
                    allowClear
                    options={[
                        { label: 'Assigned', value: 'assigned' },
                        { label: 'Unassigned', value: 'unassigned' },
                    ]}
                    onChange={(value) =>
                        setWorkflowActionConfig(node.data.id, {
                            type: 'event',
                            filters: accountRelationshipChangedFilters(selectedNames, config.filters, value),
                        })
                    }
                    data-attr="account-relationship-change-type-filter"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Available in steps" help="Reference the change from any step, filter, or condition">
                <div className="flex flex-col gap-1">
                    {RELATIONSHIP_TRIGGER_EVENT_TEMPLATES.map((template) => (
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
    value: 'account_relationship_changed',
    label: 'Account relationship changed',
    icon: <IconPerson />,
    description: 'Trigger when an account relationship is assigned or unassigned',
    group: 'Customer analytics',
    featureFlag: FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
    matchConfig: (config) => config.type === 'event' && getEventId(config) === ACCOUNT_RELATIONSHIP_CHANGED_EVENT,
    buildConfig: () => ({
        type: 'event',
        filters: accountRelationshipChangedFilters([]),
    }),
    ConfigComponent: StepTriggerConfigurationAccountRelationshipChanged,
    frequencyOptions: accountRelationshipFrequencyOptions,
    frequencyDescription: 'Limit how often each account can enter this workflow',
})
