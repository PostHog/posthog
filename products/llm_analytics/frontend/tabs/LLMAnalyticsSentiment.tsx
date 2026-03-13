import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronRight, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSkeleton, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { MessageSentimentBar, SENTIMENT_BAR_COLOR } from '../components/SentimentTag'
import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import { llmGenerationSentimentLazyLoaderLogic } from '../llmGenerationSentimentLazyLoaderLogic'
import { llmPersonsLazyLoaderLogic } from '../llmPersonsLazyLoaderLogic'
import type { GenerationSentiment, MessageSentiment } from '../llmSentimentLazyLoaderLogic'
import { capitalize, formatScore } from '../sentimentUtils'
import type { SentimentLabel } from '../sentimentUtils'
import { CompatMessage } from '../types'
import { normalizeMessages, parseJSONPreview, truncateValue } from '../utils'
import { llmAnalyticsSentimentLogic, SentimentFilterLabel, SentimentGeneration } from './llmAnalyticsSentimentLogic'

/**
 * Truncates text to show the tail (last `displayChars` characters), mirroring the backend
 * sentiment classifier which uses the last 2000 chars of each message.
 */
function truncateToClassifierWindow(text: string, displayChars: number = 200): string {
    if (text.length <= displayChars) {
        return text
    }
    return '…' + text.slice(-displayChars)
}

function extractUserMessages(aiInput: unknown): CompatMessage[] {
    try {
        const parsed = parseJSONPreview(aiInput)
        const normalized = normalizeMessages(parsed, 'user')
        return normalized.filter((msg) => msg.role === 'user' && !msg.tool_call_id)
    } catch {
        return []
    }
}

function extractTextFromBlocks(blocks: unknown[]): string {
    return blocks
        .map((block) => {
            if (typeof block === 'string') {
                return block
            }
            if (block && typeof block === 'object' && 'text' in block) {
                return (block as { text: string }).text
            }
            return ''
        })
        .filter(Boolean)
        .join('\n')
}

function getTextContent(message: CompatMessage): string {
    if (typeof message.content === 'string') {
        // Detect JSON-encoded structured content (e.g. '{"content":[{"text":"..."}]}')
        const trimmed = message.content.trim()
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
                const parsed = JSON.parse(trimmed)
                if (Array.isArray(parsed)) {
                    return extractTextFromBlocks(parsed)
                }
                if (parsed && typeof parsed === 'object' && 'content' in parsed && Array.isArray(parsed.content)) {
                    return extractTextFromBlocks(parsed.content)
                }
                if (parsed && typeof parsed === 'object' && 'text' in parsed) {
                    return (parsed as { text: string }).text
                }
            } catch {
                // Not valid JSON, return as-is
            }
        }
        return message.content
    }
    if (Array.isArray(message.content)) {
        return extractTextFromBlocks(message.content)
    }
    if (message.content && typeof message.content === 'object' && 'content' in message.content) {
        const inner = (message.content as { content: unknown }).content
        if (typeof inner === 'string') {
            return inner
        }
        if (Array.isArray(inner)) {
            return extractTextFromBlocks(inner)
        }
    }
    return ''
}

function shouldShowCard(
    sentimentData: GenerationSentiment | null | undefined,
    sentimentFilter: SentimentFilterLabel,
    intensityThreshold: number
): boolean {
    if (sentimentData === undefined || sentimentData === null) {
        return true
    }
    const label = sentimentData.label as SentimentLabel
    const score = sentimentData.score
    if (sentimentFilter !== 'both') {
        if (label !== sentimentFilter) {
            return false
        }
    } else {
        if (label === 'neutral') {
            return false
        }
    }
    if (score < intensityThreshold) {
        return false
    }
    return true
}

/** Color for the left accent bar — uses the last message's sentiment if available, else the overall */
function accentColorForMessage(
    msgSentiment: MessageSentiment | undefined,
    genSentiment: GenerationSentiment | null | undefined
): string {
    const label = msgSentiment?.label ?? genSentiment?.label
    if (!label) {
        return 'bg-border'
    }
    return SENTIMENT_BAR_COLOR[label as SentimentLabel] ?? 'bg-border'
}

interface MessageRowProps {
    text: string
    sentiment: MessageSentiment | undefined
    loading: boolean
}

function MessageRow({ text, sentiment, loading }: MessageRowProps): JSX.Element {
    const truncated = truncateToClassifierWindow(text)

    return (
        <div className="flex items-start gap-2">
            <p className="flex-1 min-w-0 text-sm text-default m-0 break-words leading-relaxed">{truncated}</p>
            <div className="shrink-0 flex items-center gap-1 pt-0.5">
                {sentiment ? (
                    <>
                        <MessageSentimentBar sentiment={sentiment} />
                        <span className="text-xs text-muted whitespace-nowrap tabular-nums">
                            {formatScore(sentiment.score)}
                        </span>
                    </>
                ) : loading ? (
                    <LemonSkeleton className="h-1.5 w-10" />
                ) : null}
            </div>
        </div>
    )
}

function SentimentGenerationCard({ generation }: { generation: SentimentGeneration }): JSX.Element {
    const { uuid, traceId, aiInput, model, distinctId, timestamp } = generation
    const { sentimentByGenerationId, isGenerationLoading } = useValues(llmGenerationSentimentLazyLoaderLogic)
    const { ensureGenerationSentimentLoaded } = useActions(llmGenerationSentimentLazyLoaderLogic)
    const { dateFilter } = useValues(llmAnalyticsSharedLogic)
    const { personsCache } = useValues(llmPersonsLazyLoaderLogic)
    const { ensurePersonLoaded } = useActions(llmPersonsLazyLoaderLogic)

    const sentimentData = sentimentByGenerationId[uuid] as GenerationSentiment | null | undefined
    const loading = isGenerationLoading(uuid)

    useEffect(() => {
        if (sentimentData === undefined && !loading) {
            ensureGenerationSentimentLoaded(uuid, dateFilter)
        }
    }, [uuid, sentimentData, loading, dateFilter, ensureGenerationSentimentLoaded])

    useEffect(() => {
        if (distinctId && personsCache[distinctId] === undefined) {
            ensurePersonLoaded(distinctId)
        }
    }, [distinctId, personsCache, ensurePersonLoaded])

    const userMessages = extractUserMessages(aiInput)
    const personData = personsCache[distinctId]
    const [expanded, setExpanded] = useState(false)

    // Prepare messages with their text content (filter out empty ones)
    const messagesWithText = userMessages
        .map((msg, idx) => ({
            text: getTextContent(msg),
            sentiment: sentimentData?.messages?.[idx] as MessageSentiment | undefined,
            idx,
        }))
        .filter((m) => m.text.length > 0)

    const lastMessage = messagesWithText[messagesWithText.length - 1]
    const earlierMessages = messagesWithText.slice(0, -1)
    const hasEarlierMessages = earlierMessages.length > 0

    return (
        <div className="flex border rounded-lg overflow-hidden" data-attr="llma-sentiment-card">
            {/* Accent bar colored by the last message's sentiment */}
            <div className={`w-1 shrink-0 ${accentColorForMessage(lastMessage?.sentiment, sentimentData)}`} />

            <div className="flex-1 min-w-0 p-3">
                {/* Earlier messages (collapsed by default) */}
                {hasEarlierMessages && (
                    <div className="mb-1">
                        <button
                            onClick={() => setExpanded(!expanded)}
                            className="flex items-center gap-1 text-xs text-muted hover:text-default cursor-pointer bg-transparent border-0 p-0 mb-1"
                        >
                            <IconChevronRight
                                className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
                            />
                            {earlierMessages.length} earlier message{earlierMessages.length > 1 ? 's' : ''}
                        </button>
                        {expanded && (
                            <div className="space-y-1.5 mb-2 pl-4 border-l border-border">
                                {earlierMessages.map((m) => (
                                    <MessageRow key={m.idx} text={m.text} sentiment={m.sentiment} loading={loading} />
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Last (most recent) user message — always visible */}
                {lastMessage ? (
                    <MessageRow text={lastMessage.text} sentiment={lastMessage.sentiment} loading={loading} />
                ) : (
                    <p className="text-muted text-sm italic m-0">No user messages</p>
                )}

                {/* Footer: sentiment label + metadata + link */}
                <div className="flex items-center gap-3 mt-2 pt-2 border-t text-xs text-muted flex-wrap">
                    {loading || sentimentData === undefined ? (
                        <LemonSkeleton className="h-4 w-20" />
                    ) : sentimentData ? (
                        <span className="font-medium">
                            {capitalize(sentimentData.label)} {formatScore(sentimentData.score)}
                        </span>
                    ) : null}

                    {model && <span>{model}</span>}

                    <TZLabel time={timestamp} />

                    {personData ? (
                        <PersonDisplay
                            person={{ distinct_id: personData.distinct_id, properties: personData.properties }}
                            withIcon
                            noPopover={false}
                        />
                    ) : (
                        distinctId && <span>{truncateValue(distinctId)}</span>
                    )}

                    <span className="flex-1" />

                    <Tooltip title={traceId}>
                        <Link
                            to={urls.llmAnalyticsTrace(traceId, { event: uuid })}
                            className="text-xs"
                            data-attr="llma-sentiment-trace-link"
                        >
                            View trace
                        </Link>
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}

function SentimentFilters(): JSX.Element {
    const { dateFilter, shouldFilterTestAccounts, propertyFilters } = useValues(llmAnalyticsSharedLogic)
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmAnalyticsSharedLogic)
    const { taxonomicGroupTypes, generationsLoading } = useValues(llmAnalyticsSentimentLogic)
    const { loadGenerations } = useActions(llmAnalyticsSentimentLogic)

    return (
        <div className="flex gap-x-4 gap-y-2 items-center flex-wrap pb-3 mb-3 border-b">
            <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
            <PropertyFilters
                propertyFilters={propertyFilters}
                taxonomicGroupTypes={taxonomicGroupTypes}
                onChange={setPropertyFilters}
                pageKey="llm-analytics-sentiment"
            />
            <div className="flex-1" />
            <TestAccountFilterSwitch checked={shouldFilterTestAccounts} onChange={setShouldFilterTestAccounts} />
            <LemonButton
                icon={<IconRefresh />}
                size="small"
                type="secondary"
                onClick={loadGenerations}
                loading={generationsLoading}
                data-attr="llma-sentiment-reload"
            >
                Reload
            </LemonButton>
        </div>
    )
}

function SentimentControls(): JSX.Element {
    const { sentimentFilter, intensityThreshold } = useValues(llmAnalyticsSentimentLogic)
    const { setSentimentFilter, setIntensityThreshold } = useActions(llmAnalyticsSentimentLogic)

    return (
        <div className="flex items-center gap-4 flex-wrap mb-3" data-attr="llma-sentiment-controls">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Show:</span>
                <LemonSegmentedButton
                    size="small"
                    value={sentimentFilter}
                    onChange={(value) => setSentimentFilter(value as SentimentFilterLabel)}
                    options={[
                        { value: 'positive', label: 'Positive' },
                        { value: 'negative', label: 'Negative' },
                        { value: 'both', label: 'Both' },
                    ]}
                    data-attr="llma-sentiment-filter"
                />
            </div>
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium whitespace-nowrap">Min intensity:</span>
                <LemonSlider
                    min={0}
                    max={1}
                    step={0.05}
                    value={intensityThreshold}
                    onChange={setIntensityThreshold}
                    className="w-24"
                />
                <span className="text-xs text-muted w-8 tabular-nums">{formatScore(intensityThreshold)}</span>
            </div>
        </div>
    )
}

export function LLMAnalyticsSentiment(): JSX.Element {
    const { generations, generationsLoading, sentimentFilter, intensityThreshold } =
        useValues(llmAnalyticsSentimentLogic)
    const { sentimentByGenerationId } = useValues(llmGenerationSentimentLazyLoaderLogic)

    const visibleGenerations = generations.filter((gen: SentimentGeneration) => {
        const sentimentData = sentimentByGenerationId[gen.uuid]
        return shouldShowCard(sentimentData, sentimentFilter, intensityThreshold)
    })

    return (
        <div data-attr="llma-sentiment-tab">
            <SentimentFilters />
            <SentimentControls />

            {generationsLoading && generations.length === 0 ? (
                <div className="flex items-center justify-center py-20">
                    <Spinner className="text-4xl" />
                </div>
            ) : generations.length === 0 ? (
                <div className="text-center py-20 text-muted">
                    <p className="text-lg font-medium mb-1">No generations with user input found</p>
                    <p className="text-sm">Try changing the date range or filters.</p>
                </div>
            ) : (
                <>
                    {visibleGenerations.length === 0 ? (
                        <div className="text-center py-10 text-muted">
                            <p className="text-sm">
                                No generations match the current sentiment filter. Try adjusting the controls above.
                            </p>
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {visibleGenerations.map((gen: SentimentGeneration) => (
                                <SentimentGenerationCard key={gen.uuid} generation={gen} />
                            ))}
                        </div>
                    )}

                    {generationsLoading && (
                        <div className="flex items-center justify-center py-4">
                            <Spinner className="text-lg" />
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
