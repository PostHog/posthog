import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconFilter } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode } from '~/queries/schema/schema-general'
import { QueryContextColumn } from '~/queries/types'
import { hogql, isDataTableNode, isEventsQuery } from '~/queries/utils'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { AIDataLoading } from './components/AIDataLoading'
import { EventData, useAIData } from './hooks/useAIData'
import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { CompatMessage } from './types'
import { normalizeMessages } from './utils'

const truncateValue = (value: string): string => {
    if (value.length > 8) {
        return `${value.substring(0, 4)}...${value.substring(value.length - 4)}`
    }
    return value
}

// Person types and utilities for filter functionality
export interface PersonData {
    distinct_id?: string
    properties?: Record<string, unknown>
}

export type FilterIdentifier =
    | { type: 'email'; value: string }
    | { type: 'username'; value: string }
    | { type: 'distinct_id'; value: string }

export function getFilterIdentifier(person: PersonData | null | undefined): FilterIdentifier | null {
    if (!person) {
        return null
    }

    const email = typeof person.properties?.email === 'string' ? person.properties.email : undefined
    const username = typeof person.properties?.username === 'string' ? person.properties.username : undefined
    const distinctId = person.distinct_id

    if (email) {
        return { type: 'email', value: email }
    }

    if (username) {
        return { type: 'username', value: username }
    }

    if (distinctId) {
        return { type: 'distinct_id', value: distinctId }
    }

    return null
}

export function createPersonFilter(filterIdentifier: FilterIdentifier): AnyPropertyFilter {
    if (filterIdentifier.type === 'distinct_id') {
        return {
            type: PropertyFilterType.HogQL,
            key: hogql`distinct_id == ${filterIdentifier.value}`,
        }
    }

    return {
        type: PropertyFilterType.Person,
        key: filterIdentifier.type,
        operator: PropertyOperator.Exact,
        value: filterIdentifier.value,
    }
}

export function getTracesUrlWithPersonFilter(
    filterIdentifier: FilterIdentifier,
    dateRange?: { dateFrom: string | null; dateTo: string | null }
): string {
    const filter = createPersonFilter(filterIdentifier)
    return combineUrl(urls.llmAnalyticsTraces(), {
        filters: [filter],
        date_from: dateRange?.dateFrom ?? undefined,
        date_to: dateRange?.dateTo ?? undefined,
    }).url
}

function PersonColumnCell({ person }: { person: PersonData | null | undefined }): JSX.Element {
    const { setPropertyFilters } = useActions(llmAnalyticsSharedLogic)
    const { propertyFilters } = useValues(llmAnalyticsSharedLogic)

    const filterIdentifier = getFilterIdentifier(person)

    const handleFilterByPerson = (e: React.MouseEvent): void => {
        e.stopPropagation()

        if (!filterIdentifier) {
            return
        }

        const newFilter = createPersonFilter(filterIdentifier)
        const filterExists = propertyFilters.some((f) => {
            if (filterIdentifier.type === 'distinct_id') {
                return f.type === PropertyFilterType.HogQL && f.key === newFilter.key
            }
            return (
                f.type === PropertyFilterType.Person &&
                f.key === filterIdentifier.type &&
                'value' in f &&
                f.value === filterIdentifier.value
            )
        })

        if (!filterExists) {
            setPropertyFilters([...propertyFilters, newFilter])
        }
    }

    return (
        <div className="flex items-center gap-1">
            <PersonDisplay person={person ?? undefined} withIcon noPopover={false} />

            {filterIdentifier && (
                <Tooltip title={`Filter by ${filterIdentifier.value}`}>
                    <LemonButton size="xsmall" icon={<IconFilter />} onClick={handleFilterByPerson} noPadding />
                </Tooltip>
            )}
        </div>
    )
}

function PersonColumnCellWithRedirect({ person }: { person: PersonData | null | undefined }): JSX.Element {
    const { push } = useActions(router)
    const { dateFilter } = useValues(llmAnalyticsSharedLogic)
    const filterIdentifier = getFilterIdentifier(person)

    const handleFilterAndRedirect = (e: React.MouseEvent): void => {
        e.stopPropagation()

        if (!filterIdentifier) {
            return
        }

        const url = getTracesUrlWithPersonFilter(filterIdentifier, dateFilter)
        push(url)
    }

    return (
        <div className="flex items-center gap-1">
            <PersonDisplay person={person ?? undefined} withIcon noPopover={false} />

            {filterIdentifier && (
                <Tooltip title={`View traces for ${filterIdentifier.value}`}>
                    <LemonButton size="xsmall" icon={<IconFilter />} onClick={handleFilterAndRedirect} noPadding />
                </Tooltip>
            )}
        </div>
    )
}

function AIInputCell({ eventData }: { eventData: EventData }): JSX.Element {
    const { input, isLoading } = useAIData(eventData)

    if (isLoading) {
        return <AIDataLoading variant="inline" />
    }

    let inputNormalized: CompatMessage[] | undefined
    try {
        const parsed = typeof input === 'string' ? JSON.parse(input) : input
        inputNormalized = normalizeMessages(parsed, 'user')
    } catch (e) {
        console.warn('Error normalizing properties.$ai_input', e)
    }

    if (!inputNormalized?.length) {
        return <>–</>
    }

    return <LLMMessageDisplay message={inputNormalized.at(-1)!} isOutput={false} minimal />
}

function AIOutputCell({ eventData }: { eventData: EventData }): JSX.Element {
    const { output, isLoading } = useAIData(eventData)

    if (isLoading) {
        return <AIDataLoading variant="inline" />
    }

    let outputNormalized: CompatMessage[] | undefined
    try {
        const parsed = typeof output === 'string' ? JSON.parse(output) : output
        outputNormalized = normalizeMessages(parsed, 'assistant')
    } catch (e) {
        console.warn('Error normalizing properties.$ai_output_choices', e)
    }

    if (!outputNormalized?.length) {
        return <>–</>
    }

    return (
        <div>
            {outputNormalized.map((message, index) => (
                <LLMMessageDisplay key={index} message={message} isOutput={true} minimal />
            ))}
        </div>
    )
}

const getEventData = (record: unknown, query?: DataTableNode | DataVisualizationNode): EventData | undefined => {
    // Object format (TracesQuery results)
    if (record && typeof record === 'object' && !Array.isArray(record) && 'uuid' in record) {
        const uuid = record.uuid
        if (typeof uuid !== 'string') {
            return undefined
        }
        const props = 'properties' in record && typeof record.properties === 'object' ? record.properties : null
        return {
            uuid,
            input: (props as Record<string, unknown> | null)?.$ai_input,
            output: (props as Record<string, unknown> | null)?.$ai_output_choices,
        }
    }

    // Array format (EventsQuery results)
    if (Array.isArray(record) && isDataTableNode(query) && isEventsQuery(query.source)) {
        const select = query.source.select ?? []
        const uuidIdx = select.findIndex((c) => c === 'uuid')
        const inputIdx = select.findIndex((c) => c === 'properties.$ai_input' || c === 'properties.$ai_input[-1]')
        const outputIdx = select.findIndex((c) => c === 'properties.$ai_output_choices')

        const uuid = record[uuidIdx]
        if (typeof uuid !== 'string') {
            return undefined
        }

        return {
            uuid,
            input: inputIdx >= 0 ? record[inputIdx] : undefined,
            output: outputIdx >= 0 ? record[outputIdx] : undefined,
        }
    }

    return undefined
}

export const llmAnalyticsColumnRenderers: Record<string, QueryContextColumn> = {
    'properties.$ai_input[-1]': {
        title: 'Input',
        render: ({ record, query }) => {
            const eventData = getEventData(record, query)
            if (!eventData) {
                return <>–</>
            }
            return <AIInputCell eventData={eventData} />
        },
    },
    'properties.$ai_input': {
        title: 'Input (full)',
        render: ({ record, query }) => {
            const eventData = getEventData(record, query)
            if (!eventData) {
                return <>–</>
            }
            return <AIInputCell eventData={eventData} />
        },
    },
    'properties.$ai_output_choices': {
        title: 'Output',
        render: ({ record, query }) => {
            const eventData = getEventData(record, query)
            if (!eventData) {
                return <>–</>
            }
            return <AIOutputCell eventData={eventData} />
        },
    },
    'properties.$ai_trace_id': {
        title: 'Trace ID',
        render: ({ value }) => {
            if (!value || typeof value !== 'string') {
                return null
            }

            const visualValue = truncateValue(value)

            return (
                <Tooltip title={value}>
                    <Link to={`/llm-analytics/traces/${value}`} data-attr="generation-trace-link">
                        {visualValue}
                    </Link>
                </Tooltip>
            )
        },
    },
    person: {
        title: 'Person',
        render: ({ value, record, query }) => {
            // Handle object format (TracesQuery results - LLMTracePerson)
            if (value && typeof value === 'object' && !Array.isArray(value) && 'distinct_id' in value) {
                return <PersonColumnCell person={value as PersonData} />
            }

            // Handle array format (EventsQuery results) - extract person from array by column index
            if (Array.isArray(record) && isDataTableNode(query) && isEventsQuery(query.source)) {
                const select = query.source.select ?? []
                const personIdx = select.findIndex((c) => c === 'person')

                if (personIdx >= 0) {
                    const personValue = record[personIdx]

                    // Person data from EventsQuery comes as a tuple [distinct_id, created_at, properties_json]
                    if (Array.isArray(personValue) && personValue.length >= 3) {
                        const [distinctId, , propertiesJson] = personValue
                        let properties: Record<string, unknown> = {}

                        try {
                            properties = typeof propertiesJson === 'string' ? JSON.parse(propertiesJson) : {}
                        } catch {
                            // Ignore parsing errors
                        }

                        return <PersonColumnCell person={{ distinct_id: distinctId, properties }} />
                    }
                }
            }

            return <PersonColumnCell person={null} />
        },
    },
    // User column for Users tab - clicking filter redirects to traces page
    user: {
        title: 'Person',
        render: ({ value }) => {
            // User data from HogQL query comes as a tuple [distinct_id, created_at, properties_json]
            if (Array.isArray(value) && value.length >= 3) {
                const [distinctId, , propertiesJson] = value
                let properties: Record<string, unknown> = {}

                try {
                    properties = typeof propertiesJson === 'string' ? JSON.parse(propertiesJson) : {}
                } catch {
                    // Ignore parsing errors
                }

                return <PersonColumnCellWithRedirect person={{ distinct_id: distinctId, properties }} />
            }

            return <PersonColumnCellWithRedirect person={null} />
        },
    },
}
