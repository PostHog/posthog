/**
 * Overview tab — the "what's this agent's situation right now" landing.
 *
 * Three sections, top-to-bottom:
 *   1. Per-agent StatStrip (live · sessions 24h · spend 24h · last fired)
 *   2. Trigger summary card (cron schedule, slack workspaces, etc.) +
 *      a quick spec snapshot (model, secrets, limits) side-by-side.
 *   3. Recent activity preview — last 5 sessions in compact rows.
 *
 * Uses primitives the agent list already established (StatStrip,
 * minimal-row layout) so the visual language stays consistent.
 */

import { CalendarClockIcon, ChevronRightIcon, GlobeIcon, HashIcon, MessageSquareIcon, WebhookIcon } from 'lucide-react'
import { useMemo } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, AgentRevisionFixture, AgentStats } from '@posthog/agent-chat/fixtures'

import { StatStrip, type StatTile } from './StatStrip'

export interface AgentOverviewProps {
    agent: AgentApplicationFixture
    liveRevision: AgentRevisionFixture | null
    stats: AgentStats
    recentSessions: ChatSession[]
    onOpenSession?: (sessionId: string) => void
    onOpenConfiguration?: () => void
    onOpenSessions?: () => void
}

export function AgentOverview({
    liveRevision,
    stats,
    recentSessions,
    onOpenSession,
    onOpenConfiguration,
    onOpenSessions,
}: AgentOverviewProps): React.ReactElement {
    // `agent` is on the props type for future use (e.g. surfacing per-agent
    // archived state inline) — header above the tabs already shows
    // name/description, so it's unused here for now.
    const tiles = useMemo<StatTile[]>(
        () => [
            {
                label: 'Live now',
                value: stats.liveCount,
                hint: stats.liveCount > 0 ? 'sessions in flight' : 'nothing running',
            },
            {
                label: 'Sessions · 24h',
                value: stats.sessions24hCount,
                hint:
                    typeof stats.failureRate24h === 'number'
                        ? `${Math.round(stats.failureRate24h * 100)}% failed`
                        : undefined,
                tone: stats.failureRate24h && stats.failureRate24h > 0 ? 'attention' : 'default',
            },
            { label: 'Spend · 24h', value: `$${stats.spend24hUsd.toFixed(2)}` },
            {
                label: 'Last activity',
                value: stats.lastActivityAt ? formatRelative(stats.lastActivityAt) : '—',
                hint: stats.lastActivityAt
                    ? new Date(stats.lastActivityAt).toLocaleString(undefined, {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                      })
                    : 'no runs yet',
            },
        ],
        [stats]
    )

    const spec = (liveRevision?.spec ?? {}) as Record<string, unknown>
    const triggers = Array.isArray(spec.triggers)
        ? (spec.triggers as Array<{ type: string; config?: Record<string, unknown> }>)
        : []
    const model = typeof spec.model === 'string' ? spec.model : null
    const secrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []

    return (
        <div className="space-y-4">
            <StatStrip tiles={tiles} />

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <OverviewCard
                    title="Triggers"
                    right={liveRevision ? <SmallLink onClick={onOpenConfiguration}>Edit in config</SmallLink> : null}
                >
                    {!liveRevision ? (
                        <EmptyHint text="No live revision yet." />
                    ) : triggers.length === 0 ? (
                        <EmptyHint text="No triggers configured." />
                    ) : (
                        <ul className="space-y-2">
                            {triggers.map((t, i) => (
                                <li key={i}>
                                    <TriggerSummary trigger={t} />
                                </li>
                            ))}
                        </ul>
                    )}
                </OverviewCard>

                <OverviewCard
                    title="Live revision"
                    right={liveRevision ? <SmallLink onClick={onOpenConfiguration}>Open config</SmallLink> : null}
                >
                    {!liveRevision ? (
                        <EmptyHint text="No live revision yet. Promote a draft to start serving." />
                    ) : (
                        <dl className="grid grid-cols-2 gap-y-1.5 text-xs">
                            <DtDd k="model" v={model ?? '—'} mono />
                            <DtDd k="revision" v={shortId(liveRevision.id)} mono />
                            <DtDd k="secrets" v={secrets.length === 0 ? 'none' : `${secrets.length} declared`} />
                            <DtDd k="promoted" v={formatRelative(liveRevision.updated_at)} />
                        </dl>
                    )}
                </OverviewCard>
            </div>

            <OverviewCard
                title="Recent activity"
                right={
                    recentSessions.length > 0 ? <SmallLink onClick={onOpenSessions}>All sessions →</SmallLink> : null
                }
            >
                {recentSessions.length === 0 ? (
                    <EmptyHint text="This agent hasn't run yet." />
                ) : (
                    <ul className="divide-y divide-border/60">
                        {recentSessions.slice(0, 5).map((s) => (
                            <li key={s.id}>
                                <RecentSessionRow session={s} onClick={() => onOpenSession?.(s.id)} />
                            </li>
                        ))}
                    </ul>
                )}
            </OverviewCard>
        </div>
    )
}

/* ── Subcomponents ───────────────────────────────────────────────── */

function OverviewCard({
    title,
    right,
    children,
}: {
    title: string
    right?: React.ReactNode
    children: React.ReactNode
}): React.ReactElement {
    return (
        <div className="overflow-hidden rounded-md border border-border bg-card">
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
                {right ? <div>{right}</div> : null}
            </div>
            <div className="px-3 py-3">{children}</div>
        </div>
    )
}

function SmallLink({ onClick, children }: { onClick?: () => void; children: React.ReactNode }): React.ReactElement {
    return (
        <button
            type="button"
            onClick={onClick}
            className="cursor-pointer text-[0.6875rem] text-muted-foreground transition-colors hover:text-foreground"
        >
            {children}
        </button>
    )
}

function EmptyHint({ text }: { text: string }): React.ReactElement {
    return <p className="text-xs italic text-muted-foreground">{text}</p>
}

function DtDd({ k, v, mono = false }: { k: string; v: string; mono?: boolean }): React.ReactElement {
    return (
        <>
            <dt className="text-muted-foreground">{k}</dt>
            <dd className={'truncate text-right text-foreground' + (mono ? ' font-mono' : '')}>{v}</dd>
        </>
    )
}

function TriggerSummary({
    trigger,
}: {
    trigger: { type: string; config?: Record<string, unknown> }
}): React.ReactElement {
    const { Icon, summary, detail } = describeTrigger(trigger)
    return (
        <div className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-2.5 py-1.5">
            <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-xs">
                    <span className="font-medium text-foreground">{trigger.type}</span>
                    <span className="truncate text-muted-foreground">{summary}</span>
                </div>
                {detail ? (
                    <div className="mt-0.5 font-mono text-[0.6875rem] text-muted-foreground">{detail}</div>
                ) : null}
            </div>
        </div>
    )
}

function describeTrigger(trigger: { type: string; config?: Record<string, unknown> }): {
    Icon: typeof CalendarClockIcon
    summary: string
    detail?: string
} {
    const cfg = trigger.config ?? {}
    switch (trigger.type) {
        case 'cron':
            return {
                Icon: CalendarClockIcon,
                summary: typeof cfg.schedule === 'string' ? cfg.schedule : 'on schedule',
                detail: typeof cfg.timezone === 'string' ? cfg.timezone : undefined,
            }
        case 'slack':
            return {
                Icon: MessageSquareIcon,
                summary: Array.isArray(cfg.trusted_workspaces)
                    ? `workspaces: ${(cfg.trusted_workspaces as string[]).join(', ')}`
                    : 'on mention',
            }
        case 'webhook':
            return {
                Icon: WebhookIcon,
                summary: typeof cfg.path === 'string' ? cfg.path : 'on POST',
            }
        case 'chat':
            return { Icon: HashIcon, summary: 'via chat trigger' }
        default:
            return { Icon: GlobeIcon, summary: '' }
    }
}

function RecentSessionRow({ session, onClick }: { session: ChatSession; onClick?: () => void }): React.ReactElement {
    const tone = stateTone(session.state)
    // Prefer the user's task; the list endpoint only returns a preview
    // (last assistant text), so fall back to that when there's no
    // hydrated user turn.
    const taskLine = firstUserText(session) ?? firstAssistantText(session) ?? '—'
    return (
        <button
            type="button"
            onClick={onClick}
            className="group flex w-full cursor-pointer items-center gap-3 px-1 py-2 text-left transition-colors hover:bg-accent/40 focus-visible:bg-accent/40 focus-visible:outline-none"
        >
            <span className={`mt-1 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1">
                <p className="line-clamp-1 text-xs text-foreground">{taskLine}</p>
                <div className="mt-0.5 flex items-center gap-2 text-[0.6875rem] text-muted-foreground">
                    <span>{tone.label}</span>
                    <span>·</span>
                    <span>{session.principal.displayName}</span>
                    {session.started_at ? (
                        <>
                            <span>·</span>
                            <span>{formatRelative(session.started_at)}</span>
                        </>
                    ) : null}
                </div>
            </div>
            <span className="shrink-0 font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
                ${session.usage.costUsd.toFixed(3)}
            </span>
            <ChevronRightIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
        </button>
    )
}

function stateTone(state: ChatSession['state']): { dotClass: string; label: string } {
    // Same reasoning as SessionsList — `*-foreground` is the saturated
    // medium tone that reads on the light surface.
    switch (state) {
        case 'streaming':
            return { dotClass: 'bg-info-foreground animate-pulse', label: 'streaming' }
        case 'awaiting_user_input':
            return { dotClass: 'bg-warning-foreground', label: 'awaiting user input' }
        case 'awaiting_client_tool':
            return { dotClass: 'bg-info-foreground', label: 'awaiting client' }
        case 'completed':
            return { dotClass: 'bg-success-foreground', label: 'completed' }
        case 'failed':
        case 'error':
            return { dotClass: 'bg-destructive-foreground', label: state }
        case 'cancelled':
            return { dotClass: 'bg-muted-foreground/60', label: 'cancelled' }
        case 'disconnected':
            return { dotClass: 'bg-muted-foreground/60', label: 'disconnected' }
        case 'idle':
        default:
            return { dotClass: 'bg-success-foreground', label: 'idle' }
    }
}

function firstUserText(session: ChatSession): string | null {
    for (const turn of session.turns) {
        if (turn.kind === 'user') {
            return turn.text
        }
    }
    return null
}

function firstAssistantText(session: ChatSession): string | null {
    for (const turn of session.turns) {
        if (turn.kind === 'assistant') {
            for (const p of turn.parts) {
                if (p.kind === 'text') {
                    return p.text
                }
            }
        }
    }
    return null
}

/**
 * Last hyphen-separated chunk of a UUID, truncated to 8 chars. Used as
 * a human-friendly handle for revisions in the overview card.
 *
 * Exported (vs being a private `function short(...)`) because the
 * SWC dev compiler doesn't always hoist function declarations
 * referenced from JSX above their definition — the named import
 * dodges the issue.
 */
export function shortId(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

function formatRelative(iso: string): string {
    const ts = new Date(iso).getTime()
    if (!ts) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - ts)
    const minute = 60 * 1000
    const hour = 60 * minute
    const day = 24 * hour
    if (diff < minute) {
        return 'just now'
    }
    if (diff < hour) {
        return `${Math.floor(diff / minute)}m ago`
    }
    if (diff < day) {
        return `${Math.floor(diff / hour)}h ago`
    }
    return `${Math.floor(diff / day)}d ago`
}
