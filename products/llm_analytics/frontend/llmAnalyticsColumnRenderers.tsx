import { Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { QueryContextColumn } from '~/queries/types'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { AIDataLoading } from './components/AIDataLoading'
import { useAIData } from './hooks/useAIData'
import { CompatMessage } from './types'
import { normalizeMessages } from './utils'

const truncateValue = (value: string): string => {
    if (value.length > 8) {
        return `${value.substring(0, 4)}...${value.substring(value.length - 4)}`
    }
    return value
}

interface AIInputCellProps {
    value: unknown
    eventId: string
}

function AIInputCell({ value, eventId }: AIInputCellProps): JSX.Element {
    const { input, isLoading } = useAIData({
        uuid: eventId,
        properties: {
            $ai_input: value,
        },
    })

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

interface AIOutputCellProps {
    value: unknown
    eventId: string
}

function AIOutputCell({ value, eventId }: AIOutputCellProps): JSX.Element {
    const { output, isLoading } = useAIData({
        uuid: eventId,
        properties: {
            $ai_output_choices: value,
        },
    })

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

const getEventId = (record: unknown): string | undefined => {
    if (record && typeof record === 'object' && 'uuid' in record && typeof record.uuid === 'string') {
        return record.uuid
    }
    return undefined
}

export const llmAnalyticsColumnRenderers: Record<string, QueryContextColumn> = {
    'properties.$ai_input[-1]': {
        title: 'Input',
        render: ({ value, record }) => {
            const eventId = getEventId(record)
            if (!eventId) {
                return <>–</>
            }
            return <AIInputCell value={value} eventId={eventId} />
        },
    },
    'properties.$ai_input': {
        title: 'Input (full)',
        render: ({ value, record }) => {
            const eventId = getEventId(record)
            if (!eventId) {
                return <>–</>
            }
            return <AIInputCell value={value} eventId={eventId} />
        },
    },
    'properties.$ai_output_choices': {
        title: 'Output',
        render: ({ value, record }) => {
            const eventId = getEventId(record)
            if (!eventId) {
                return <>–</>
            }
            return <AIOutputCell value={value} eventId={eventId} />
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
