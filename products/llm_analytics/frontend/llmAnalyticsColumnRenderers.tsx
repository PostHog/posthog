import { Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DataTableNode, DataVisualizationNode } from '~/queries/schema/schema-general'
import { QueryContextColumn } from '~/queries/types'
import { isDataTableNode, isEventsQuery } from '~/queries/utils'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { AIDataLoading } from './components/AIDataLoading'
import { EventData, useAIData } from './hooks/useAIData'
import { CompatMessage } from './types'
import { normalizeMessages } from './utils'

const truncateValue = (value: string): string => {
    if (value.length > 8) {
        return `${value.substring(0, 4)}...${value.substring(value.length - 4)}`
    }
    return value
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
}
