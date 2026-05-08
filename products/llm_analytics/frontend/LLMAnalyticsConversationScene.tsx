import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconAIText, IconCode, IconPerson, IconPlay, IconReceipt } from '@posthog/icons'
import { LemonTag, SpinnerOverlay, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { ConversationTurn, llmAnalyticsConversationDataLogic } from './llmAnalyticsConversationDataLogic'
import { llmAnalyticsConversationLogic } from './llmAnalyticsConversationLogic'
import { CompatMessage } from './types'
import { formatLLMCost, getTraceTimestamp, normalizeMessages, sanitizeTraceUrlSearchParams } from './utils'

export const scene: SceneExport = {
    component: LLMAnalyticsConversationScene,
    logic: llmAnalyticsConversationLogic,
}

export function LLMAnalyticsConversationScene({ tabId }: { tabId?: string }): JSX.Element {
    const conversationLogic = llmAnalyticsConversationLogic({ tabId })
    const { conversationRef } = useValues(conversationLogic)

    if (!conversationRef) {
        return <SpinnerOverlay />
    }

    return (
        <BindLogic logic={llmAnalyticsConversationLogic} props={{ tabId }}>
            <BindLogic
                logic={llmAnalyticsConversationDataLogic}
                props={{ kind: conversationRef.kind, id: conversationRef.id, tabId }}
            >
                <ConversationSceneContent />
            </BindLogic>
        </BindLogic>
    )
}

function normalizeTurnMessages(messages: unknown[], defaultRole: string): CompatMessage[] {
    // The backend forwards raw `$ai_input` / `$ai_output_choices` blobs (typed as
    // `unknown[]` from the JSONField serializer). `normalizeMessages` already does
    // the runtime narrowing — it accepts any value and figures out the shape.
    return normalizeMessages(messages, defaultRole)
}

interface MetadataChipProps {
    icon: JSX.Element
    label: string
    children: React.ReactNode
    to?: string
}

function MetadataChip({ icon, label, children, to }: MetadataChipProps): JSX.Element {
    const tag = (
        <LemonTag size="small" className="bg-surface-primary" icon={icon}>
            <span className="sr-only">{label}: </span>
            {children}
        </LemonTag>
    )
    return (
        <Tooltip title={to ? `${label} (click to open)` : label}>
            {to ? (
                <Link to={to} className="no-underline">
                    {tag}
                </Link>
            ) : (
                tag
            )}
        </Tooltip>
    )
}

function ConversationSceneContent(): JSX.Element {
    const { conversationRef } = useValues(llmAnalyticsConversationLogic)
    const { detail, loading, error } = useValues(llmAnalyticsConversationDataLogic)
    const { searchParams } = useValues(router)
    const traceSearchParams = sanitizeTraceUrlSearchParams(searchParams, { removeSearch: true })

    if (loading) {
        return <SpinnerOverlay />
    }
    if (error) {
        return <InsightErrorState />
    }
    if (!conversationRef || !detail || detail.turns.length === 0) {
        return (
            <InsightEmptyState
                heading="No conversation found"
                detail="There are no AI events for this conversation in the lookup window."
            />
        )
    }

    const isSession = detail.kind === 'session'
    const turnCount = detail.turns.length
    const idChipUrl = isSession
        ? combineUrl(urls.llmAnalyticsSession(detail.id), traceSearchParams).url
        : combineUrl(urls.llmAnalyticsTrace(detail.id), {
              ...traceSearchParams,
              timestamp: detail.turns[0] ? getTraceTimestamp(detail.turns[0].created_at) : undefined,
          }).url

    return (
        <div className="relative flex flex-col gap-4">
            <SceneBreadcrumbBackButton />

            <header className="flex flex-col gap-2">
                <h1 className="text-lg font-semibold m-0 truncate" title={detail.title || detail.id}>
                    {detail.title || detail.id}
                </h1>
                <div className="flex items-center gap-1.5 flex-wrap">
                    <MetadataChip
                        icon={<IconCode />}
                        label={isSession ? 'Open session detail' : 'Open trace detail'}
                        to={idChipUrl}
                    >
                        <span className="font-mono">{detail.id}</span>
                    </MetadataChip>
                    <MetadataChip icon={<IconAIText />} label="Number of turns">
                        {turnCount} {turnCount === 1 ? 'turn' : 'turns'}
                    </MetadataChip>
                    {detail.total_cost != null && detail.total_cost > 0 && (
                        <MetadataChip icon={<IconReceipt />} label="Total cost">
                            {formatLLMCost(detail.total_cost)}
                        </MetadataChip>
                    )}
                    {detail.distinct_id && (
                        <MetadataChip
                            icon={<IconPerson />}
                            label="Open user profile"
                            to={urls.personByDistinctId(detail.distinct_id)}
                        >
                            <span className="font-mono text-xs">{detail.distinct_id}</span>
                        </MetadataChip>
                    )}
                </div>
            </header>

            <div className="flex flex-col gap-2">
                {detail.turns.map((turn: ConversationTurn, idx: number) => (
                    <TurnCard key={turn.trace_id} turn={turn} index={idx} traceSearchParams={traceSearchParams} />
                ))}
            </div>
        </div>
    )
}

interface TurnCardProps {
    turn: ConversationTurn
    index: number
    traceSearchParams: Record<string, unknown>
}

function TurnCard({ turn, index, traceSearchParams }: TurnCardProps): JSX.Element {
    const userMessages = normalizeTurnMessages(turn.user_messages, 'user')
    const assistantMessages = normalizeTurnMessages(turn.assistant_messages, 'assistant')

    return (
        <div className="bg-surface-primary border rounded overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 bg-bg-light border-b text-xs">
                <div className="flex items-center gap-1.5 text-muted font-medium">
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-[var(--color-bg-fill-tertiary)] text-[11px] font-medium text-muted tabular-nums">
                        {index + 1}
                    </span>
                    <TZLabel time={turn.created_at} />
                </div>
                {turn.error_count > 0 && (
                    <LemonTag type="danger" size="small">
                        {turn.error_count === 1 ? '1 error' : `${turn.error_count} errors`}
                    </LemonTag>
                )}
                {turn.total_latency != null && turn.total_latency > 0 && (
                    <span className="text-muted tabular-nums">{turn.total_latency.toFixed(2)}s</span>
                )}
                {turn.total_cost != null && turn.total_cost > 0 && (
                    <span className="text-muted tabular-nums">{formatLLMCost(turn.total_cost)}</span>
                )}
                <span className="grow" />
                <Link
                    to={
                        combineUrl(urls.llmAnalyticsTrace(turn.trace_id), {
                            ...traceSearchParams,
                            timestamp: getTraceTimestamp(turn.created_at),
                        }).url
                    }
                    className="text-xs"
                >
                    Open trace
                </Link>
                {turn.session_id && (
                    <Link to={urls.replaySingle(turn.session_id)} className="text-xs inline-flex items-center gap-1">
                        <IconPlay /> Watch replay
                    </Link>
                )}
            </div>

            <div className="flex flex-col gap-3 p-4">
                {userMessages.length === 0 && assistantMessages.length === 0 ? (
                    <div className="text-xs text-muted italic px-1">(no messages in this turn)</div>
                ) : (
                    <>
                        {userMessages.map((msg, i) => (
                            <ChatBubble key={`u-${i}`} message={msg} align="right" />
                        ))}
                        {assistantMessages.map((msg, i) => (
                            <ChatBubble key={`a-${i}`} message={msg} align="left" />
                        ))}
                    </>
                )}
            </div>
        </div>
    )
}

/**
 * WhatsApp-style chat bubble. User messages align right, assistant left.
 * Subtle neutral surface (no role-specific colors) — the alignment is the
 * primary signal for who said what.
 *
 * Falls back to a plain JSON serialization for structured (non-string,
 * non-text-array) content; users who want the full structure click "Show
 * reasoning" for the trace event tree.
 */
function ChatBubble({ message, align }: { message: CompatMessage; align: 'left' | 'right' }): JSX.Element {
    const text = extractMessageText(message)
    const hasText = text && text.trim().length > 0

    return (
        <div className={clsx('flex w-full', align === 'right' ? 'justify-end' : 'justify-start')}>
            <div
                className={clsx(
                    'max-w-[85%] rounded-lg px-3 py-2 text-sm bg-[var(--color-bg-fill-tertiary)]',
                    align === 'right' ? 'rounded-tr-none' : 'rounded-tl-none'
                )}
            >
                {hasText ? (
                    <LemonMarkdown className="whitespace-pre-wrap break-words">{text!}</LemonMarkdown>
                ) : (
                    <span className="text-muted italic text-xs">
                        (structured content — open "Show reasoning" for details)
                    </span>
                )}
            </div>
        </div>
    )
}

/**
 * Best-effort string extraction from a message's content. Handles:
 *   - plain string
 *   - text-only array (multimodal: pulls out `text` parts)
 *   - object with a `content` string field
 * Returns null for shapes that can't be flattened to text.
 */
function extractMessageText(message: CompatMessage): string | null {
    const content = message.content
    if (content == null) {
        return null
    }
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        const parts = content
            .map((item) => {
                if (typeof item === 'string') {
                    return item
                }
                if (item && typeof item === 'object') {
                    if ('text' in item && typeof (item as any).text === 'string') {
                        return (item as any).text
                    }
                    if ('transcript' in item && typeof (item as any).transcript === 'string') {
                        return (item as any).transcript
                    }
                }
                return null
            })
            .filter((part): part is string => part != null && part.length > 0)
        return parts.length > 0 ? parts.join('\n\n') : null
    }
    if (typeof content === 'object' && 'content' in content && typeof (content as any).content === 'string') {
        return (content as any).content
    }
    return null
}
