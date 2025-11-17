import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { EventDetails } from '~/scenes/activity/explore/EventDetails'
import { EventType } from '~/types'

import { formatLLMCost } from '../utils'

interface LLMAnalyticsEventCardProps {
    event: {
        id: string
        event: string
        createdAt: string
        properties: Record<string, any>
    }
    isExpanded: boolean
    onToggleExpand: () => void
}

export function LLMAnalyticsEventCard({ event, isExpanded, onToggleExpand }: LLMAnalyticsEventCardProps): JSX.Element {
    const isGeneration = event.event === '$ai_generation'
    const isEmbedding = event.event === '$ai_embedding'
    const eventForDetails: EventType = {
        id: event.id,
        distinct_id: '',
        properties: event.properties,
        event: event.event,
        timestamp: event.createdAt,
        elements: [],
    }
    const latency = event.properties.$ai_latency
    const hasError = event.properties.$ai_error || event.properties.$ai_is_error

    // Generation-specific properties
    const model = event.properties.$ai_model || 'Unknown model'
    const cost = event.properties.$ai_total_cost_usd

    // Span-specific properties
    const spanName = event.properties.$ai_span_name || 'Unnamed span'

    return (
        <div className="border rounded bg-bg-3000">
            <div className="p-2 hover:bg-side-light cursor-pointer flex items-center gap-2" onClick={onToggleExpand}>
                <div className="flex-shrink-0">
                    {isExpanded ? (
                        <IconChevronDown className="text-base" />
                    ) : (
                        <IconChevronRight className="text-base" />
                    )}
                </div>
                <div className="flex-1 flex items-center gap-2 flex-wrap min-w-0">
                    <LemonTag
                        type={isGeneration ? 'success' : isEmbedding ? 'warning' : 'default'}
                        size="small"
                        className="uppercase"
                    >
                        {isGeneration ? 'Generation' : isEmbedding ? 'Embedding' : 'Span'}
                    </LemonTag>
                    {hasError && (
                        <LemonTag type="danger" size="small">
                            Error
                        </LemonTag>
                    )}
                    <span className="text-xs truncate">{isGeneration || isEmbedding ? model : spanName}</span>
                    {typeof latency === 'number' && (
                        <LemonTag type="muted" size="small">
                            {latency.toFixed(2)}s
                        </LemonTag>
                    )}
                    {(isGeneration || isEmbedding) && typeof cost === 'number' && (
                        <LemonTag type="muted" size="small">
                            {formatLLMCost(cost)}
                        </LemonTag>
                    )}
                </div>
            </div>
            {isExpanded && (
                <div className="border-t">
                    <EventDetails event={eventForDetails} />
                </div>
            )}
        </div>
    )
}
