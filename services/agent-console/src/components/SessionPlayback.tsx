/**
 * `<SessionPlayback />` — replays a session's turns in a UI that
 * matches its trigger.
 *
 * Same data (`session.turns[]`) drives every variant; only the shell
 * differs. This is the consumer-facing view: "what did this
 * conversation look like in its native habitat" rather than "what
 * was the runtime doing" (that's the SessionLogs pane).
 *
 * Variants by `session.trigger.kind`:
 *
 *   - **chat**   → Claude-style alternating bubbles (user vs assistant),
 *                  no avatars, monospace timestamps in a side rail.
 *   - **slack**  → Slack thread: channel header, root message,
 *                  threaded bot replies with username + emoji avatar.
 *   - **cron**   → Autonomous-run banner ("fired at … via cron 0 9 * * MON")
 *                  then collapsed assistant turns (no user, since none
 *                  prompted it interactively).
 *   - **webhook** → Webhook banner with source + path, then assistant turns.
 *   - **(missing trigger)** → falls back to chat-style.
 *
 * Cross-linking: every tool-call part has a `callId` that matches a
 * field on the SessionLogs pane. Click handlers surface `callId` via
 * `onSelectCallId` so the parent can scroll the log pane to match.
 */

'use client'

import { BotIcon, CalendarClockIcon, ChevronDownIcon, ChevronRightIcon, HashIcon, WebhookIcon } from 'lucide-react'
import { useState } from 'react'

import type { AssistantTurnPart, ChatSession, SessionTrigger, Turn } from '@posthog/agent-chat'
import { JsonView } from '@posthog/agent-chat'

export interface SessionPlaybackProps {
    session: ChatSession
    /** Highlight the turn part referencing this callId (cross-link from logs). */
    highlightedCallId?: string | null
    /** Fired when the user clicks a tool-call card — scrolls the log pane to match. */
    onSelectCallId?: (callId: string) => void
}

export function SessionPlayback({
    session,
    highlightedCallId,
    onSelectCallId,
}: SessionPlaybackProps): React.ReactElement {
    const trigger: SessionTrigger = session.trigger ?? { kind: 'chat' }

    return (
        <div className="flex h-full flex-col overflow-hidden rounded-md border border-border bg-background">
            <TriggerHeader trigger={trigger} agentName={session.application.name} />
            <div className="flex-1 overflow-y-auto px-4 py-4">
                {trigger.kind === 'slack' ? (
                    <SlackThread
                        session={session}
                        trigger={trigger}
                        highlightedCallId={highlightedCallId}
                        onSelectCallId={onSelectCallId}
                    />
                ) : (
                    <ChatTranscript
                        session={session}
                        highlightedCallId={highlightedCallId}
                        onSelectCallId={onSelectCallId}
                    />
                )}
            </div>
        </div>
    )
}

/* ── Trigger header ─────────────────────────────────────────────── */

function TriggerHeader({ trigger, agentName }: { trigger: SessionTrigger; agentName: string }): React.ReactElement {
    if (trigger.kind === 'slack') {
        return (
            <div className="flex items-center gap-2 border-b border-border bg-muted/20 px-4 py-2 text-xs">
                <HashIcon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="font-medium">{trigger.channelName}</span>
                <span className="text-muted-foreground">· {trigger.workspace}</span>
                <span className="ml-auto text-[0.6875rem] text-muted-foreground">slack thread</span>
            </div>
        )
    }
    if (trigger.kind === 'cron') {
        return (
            <div className="flex items-center gap-2 border-b border-border bg-muted/20 px-4 py-2 text-xs">
                <CalendarClockIcon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="font-medium">cron</span>
                <code className="text-[0.6875rem] text-muted-foreground">{trigger.schedule}</code>
                {trigger.timezone ? (
                    <span className="text-[0.6875rem] text-muted-foreground">· {trigger.timezone}</span>
                ) : null}
                <span className="ml-auto text-[0.6875rem] text-muted-foreground">autonomous run</span>
            </div>
        )
    }
    if (trigger.kind === 'webhook') {
        return (
            <div className="flex items-center gap-2 border-b border-border bg-muted/20 px-4 py-2 text-xs">
                <WebhookIcon className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="font-medium">webhook</span>
                <code className="text-[0.6875rem] text-muted-foreground">{trigger.path}</code>
                {trigger.source ? (
                    <span className="text-[0.6875rem] text-muted-foreground">· {trigger.source}</span>
                ) : null}
                <span className="ml-auto text-[0.6875rem] text-muted-foreground">incoming POST</span>
            </div>
        )
    }
    return (
        <div className="flex items-center gap-2 border-b border-border bg-muted/20 px-4 py-2 text-xs">
            <BotIcon className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-medium">{agentName}</span>
            <span className="ml-auto text-[0.6875rem] text-muted-foreground">chat session</span>
        </div>
    )
}

/* ── Chat (Claude-style) ────────────────────────────────────────── */

function ChatTranscript({
    session,
    highlightedCallId,
    onSelectCallId,
}: {
    session: ChatSession
    highlightedCallId?: string | null
    onSelectCallId?: (callId: string) => void
}): React.ReactElement {
    if (session.turns.length === 0) {
        return <EmptyTranscript />
    }
    return (
        <div className="space-y-5">
            {session.turns.map((turn) => (
                <ChatTurn
                    key={turn.id}
                    turn={turn}
                    highlightedCallId={highlightedCallId}
                    onSelectCallId={onSelectCallId}
                />
            ))}
        </div>
    )
}

function ChatTurn({
    turn,
    highlightedCallId,
    onSelectCallId,
}: {
    turn: Turn
    highlightedCallId?: string | null
    onSelectCallId?: (callId: string) => void
}): React.ReactElement {
    if (turn.kind === 'user') {
        return (
            <div className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-primary px-3 py-2 text-sm leading-relaxed text-primary-foreground">
                    {turn.text}
                </div>
            </div>
        )
    }
    return (
        <div className="space-y-2 pr-6">
            <Timestamp ts={turn.timestamp} />
            <div className="space-y-2">
                {turn.parts.map((part, i) => (
                    <PartRenderer
                        key={i}
                        part={part}
                        highlightedCallId={highlightedCallId}
                        onSelectCallId={onSelectCallId}
                    />
                ))}
            </div>
        </div>
    )
}

/* ── Slack thread ───────────────────────────────────────────────── */

function SlackThread({
    session,
    trigger,
    highlightedCallId,
    onSelectCallId,
}: {
    session: ChatSession
    trigger: Extract<SessionTrigger, { kind: 'slack' }>
    highlightedCallId?: string | null
    onSelectCallId?: (callId: string) => void
}): React.ReactElement {
    const userTurn = session.turns.find((t) => t.kind === 'user')
    const assistantTurns = session.turns.filter((t) => t.kind === 'assistant') as Array<
        Extract<Turn, { kind: 'assistant' }>
    >
    const rootMessage = userTurn?.kind === 'user' ? userTurn.text : trigger.rootMessage

    return (
        <div className="space-y-4">
            <SlackMessage
                author={trigger.invokedBy}
                ts={userTurn?.timestamp ?? session.started_at}
                text={rootMessage}
            />
            <div className="border-l-2 border-border/60 pl-4">
                <div className="mb-2 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                    Thread · {assistantTurns.length} {assistantTurns.length === 1 ? 'reply' : 'replies'}
                </div>
                <div className="space-y-3">
                    {assistantTurns.map((turn) => (
                        <SlackAssistantReply
                            key={turn.id}
                            turn={turn}
                            agentName={session.application.name}
                            highlightedCallId={highlightedCallId}
                            onSelectCallId={onSelectCallId}
                        />
                    ))}
                    {assistantTurns.length === 0 ? (
                        <div className="text-xs italic text-muted-foreground">No replies yet.</div>
                    ) : null}
                </div>
            </div>
        </div>
    )
}

function SlackMessage({
    author,
    ts,
    text,
    bot = false,
}: {
    author: string
    ts?: string
    text: string
    bot?: boolean
}): React.ReactElement {
    return (
        <div className="flex items-start gap-2.5">
            <SlackAvatar name={author} bot={bot} />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                    <span className="text-sm font-medium">{author}</span>
                    {bot ? (
                        <span className="rounded-sm bg-muted px-1 text-[0.5625rem] uppercase tracking-wide text-muted-foreground">
                            app
                        </span>
                    ) : null}
                    {ts ? <Timestamp ts={ts} inline /> : null}
                </div>
                <div className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed">{text}</div>
            </div>
        </div>
    )
}

function SlackAssistantReply({
    turn,
    agentName,
    highlightedCallId,
    onSelectCallId,
}: {
    turn: Extract<Turn, { kind: 'assistant' }>
    agentName: string
    highlightedCallId?: string | null
    onSelectCallId?: (callId: string) => void
}): React.ReactElement {
    return (
        <div className="flex items-start gap-2.5">
            <SlackAvatar name={agentName} bot />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                    <span className="text-sm font-medium">{agentName}</span>
                    <span className="rounded-sm bg-muted px-1 text-[0.5625rem] uppercase tracking-wide text-muted-foreground">
                        app
                    </span>
                    <Timestamp ts={turn.timestamp} inline />
                </div>
                <div className="mt-1 space-y-2">
                    {turn.parts.map((part, i) => (
                        <PartRenderer
                            key={i}
                            part={part}
                            highlightedCallId={highlightedCallId}
                            onSelectCallId={onSelectCallId}
                            slack
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}

function SlackAvatar({ name, bot = false }: { name: string; bot?: boolean }): React.ReactElement {
    const initials = name
        .split(' ')
        .map((s) => s[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    return (
        <div
            className={
                (bot ? 'bg-info text-info-foreground' : 'bg-muted text-foreground') +
                ' inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[0.6875rem] font-medium'
            }
            aria-hidden
        >
            {bot ? <BotIcon className="h-3.5 w-3.5" /> : initials}
        </div>
    )
}

/* ── Shared part renderer ───────────────────────────────────────── */

function PartRenderer({
    part,
    highlightedCallId,
    onSelectCallId,
    slack = false,
}: {
    part: AssistantTurnPart
    highlightedCallId?: string | null
    onSelectCallId?: (callId: string) => void
    slack?: boolean
}): React.ReactElement {
    if (part.kind === 'text') {
        return (
            <div
                className={
                    slack
                        ? 'whitespace-pre-wrap text-sm leading-relaxed'
                        : 'whitespace-pre-wrap rounded-2xl rounded-tl-md bg-muted/40 px-3 py-2 text-sm leading-relaxed'
                }
            >
                {part.text}
            </div>
        )
    }
    if (part.kind === 'thinking') {
        return <ThinkingPart text={part.text} />
    }
    return <ToolCallCard part={part} highlighted={highlightedCallId === part.callId} onSelectCallId={onSelectCallId} />
}

function ThinkingPart({ text }: { text: string }): React.ReactElement {
    const [open, setOpen] = useState(false)
    return (
        <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex w-full cursor-pointer items-start gap-1.5 rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/30"
        >
            {open ? (
                <ChevronDownIcon className="mt-0.5 h-3 w-3 shrink-0" />
            ) : (
                <ChevronRightIcon className="mt-0.5 h-3 w-3 shrink-0" />
            )}
            <span className={open ? 'whitespace-pre-wrap' : 'line-clamp-1'}>
                <span className="font-medium text-foreground/70">Thinking · </span>
                {text}
            </span>
        </button>
    )
}

function ToolCallCard({
    part,
    highlighted,
    onSelectCallId,
}: {
    part: Extract<AssistantTurnPart, { kind: 'tool_call' }>
    highlighted: boolean
    onSelectCallId?: (callId: string) => void
}): React.ReactElement {
    const [open, setOpen] = useState(false)
    const inFlight = part.result === undefined
    const failed = part.result !== undefined && !part.result.ok
    const dotClass = inFlight ? 'bg-muted-foreground/60 animate-pulse' : failed ? 'bg-destructive' : 'bg-success'

    return (
        <div
            className={
                'rounded-md border text-xs transition-colors ' +
                (highlighted ? 'border-info bg-info/10' : 'border-border/60 bg-muted/20')
            }
            data-call-id={part.callId}
            id={`call-${part.callId}`}
        >
            <button
                type="button"
                onClick={() => {
                    setOpen((o) => !o)
                    onSelectCallId?.(part.callId)
                }}
                className="flex w-full cursor-pointer items-center gap-2 px-2.5 py-1.5 text-left"
            >
                <span className={`inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} aria-hidden />
                <code className="truncate font-medium">{part.toolId}</code>
                {part.fulfillment === 'client' ? (
                    <span className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">client</span>
                ) : null}
                <span className="ml-auto text-muted-foreground">
                    {open ? <ChevronDownIcon className="h-3 w-3" /> : <ChevronRightIcon className="h-3 w-3" />}
                </span>
            </button>
            {open ? (
                <div className="space-y-2 border-t border-border/60 px-2.5 py-2">
                    <Labeled label="args">
                        <JsonView value={part.args} expandToLevel={1} />
                    </Labeled>
                    {part.result !== undefined ? (
                        <Labeled label="result">
                            <JsonView value={part.result} expandToLevel={1} />
                        </Labeled>
                    ) : null}
                </div>
            ) : null}
        </div>
    )
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
    return (
        <div>
            <div className="mb-1 text-[0.625rem] uppercase tracking-wide text-muted-foreground">{label}</div>
            {children}
        </div>
    )
}

function Timestamp({ ts, inline = false }: { ts: string; inline?: boolean }): React.ReactElement {
    const formatted = new Date(ts).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit' })
    if (inline) {
        return <span className="font-mono text-[0.6875rem] text-muted-foreground">{formatted}</span>
    }
    return <div className="font-mono text-[0.6875rem] text-muted-foreground">{formatted}</div>
}

function EmptyTranscript(): React.ReactElement {
    return (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            No turns yet — session is just starting.
        </div>
    )
}
