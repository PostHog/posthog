/**
 * `<ConnectionsTab>` — app-level wiring view (read-only v1).
 *
 * "What does this agent need to operate?" — secrets, team integrations,
 * and runtime MCP servers. Source of truth for the lists is the live
 * revision's spec; status badges are best-effort and noted as
 * placeholders where we don't yet have a backing endpoint.
 *
 * Editing (set / rotate / clear secrets, wire integrations, configure
 * MCPs) is the next phase — see the follow-up plan doc that will land
 * alongside the editor implementation.
 */

'use client'

import { AlertCircleIcon, KeyIcon, LinkIcon, ServerIcon } from 'lucide-react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

interface ConnectionsTabProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
}

interface McpRefAgent {
    kind: 'agent'
    slug: string
}
interface McpRefExternal {
    kind: 'external'
    url: string
    auth?: { integration?: string }
}
type McpRef = McpRefAgent | McpRefExternal

export function ConnectionsTab({ agent, revisions }: ConnectionsTabProps): React.ReactElement {
    const liveRevision = revisions.find((r) => r.id === agent.live_revision) ?? null
    // If there's no live revision, fall back to the most recent draft so the
    // page isn't blank — surface the fact clearly in the header.
    const sortedRevs = [...revisions].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    )
    const reference = liveRevision ?? sortedRevs[0] ?? null

    if (!reference) {
        return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                No revisions yet — connections will appear once a revision is published.
            </div>
        )
    }

    const spec = reference.spec as Record<string, unknown>
    const secrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []
    const integrations = Array.isArray(spec.integrations) ? (spec.integrations as string[]) : []
    const mcps = Array.isArray(spec.mcps) ? (spec.mcps as McpRef[]) : []

    return (
        <div className="space-y-4">
            {!liveRevision ? (
                <div className="flex items-start gap-2 rounded-md border border-warning-foreground/30 bg-warning/40 px-3 py-2 text-xs">
                    <AlertCircleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning-foreground" />
                    <div>
                        <p className="font-medium">Showing the latest draft</p>
                        <p className="text-muted-foreground">
                            No live revision yet. The lists below are pulled from the most recent draft — connections
                            only become load-bearing when a revision is promoted to live.
                        </p>
                    </div>
                </div>
            ) : null}

            <SecretsCard secrets={secrets} />
            <IntegrationsCard integrations={integrations} />
            <McpsCard mcps={mcps} />
        </div>
    )
}

function SecretsCard({ secrets }: { secrets: string[] }): React.ReactElement {
    return (
        <ConnectionCard
            icon={<KeyIcon className="h-3.5 w-3.5" />}
            title="Secrets"
            count={secrets.length}
            description="Encrypted env values the agent decrypts at session start. Names are declared on the spec; values live on the application."
        >
            {secrets.length === 0 ? (
                <EmptyState>No secrets declared.</EmptyState>
            ) : (
                <ul className="divide-y divide-border">
                    {secrets.map((name) => (
                        <li key={name} className="flex items-center justify-between px-3 py-2 text-xs">
                            <code className="font-mono">{name}</code>
                            <StatusBadge tone="muted">unknown</StatusBadge>
                        </li>
                    ))}
                </ul>
            )}
            <FollowupNote>
                Set / rotate / clear UI lands in the next phase. Today the runner reads values from the encrypted env
                block; this tab can't yet show set-vs-unset.
            </FollowupNote>
        </ConnectionCard>
    )
}

function IntegrationsCard({ integrations }: { integrations: string[] }): React.ReactElement {
    return (
        <ConnectionCard
            icon={<LinkIcon className="h-3.5 w-3.5" />}
            title="Integrations"
            count={integrations.length}
            description="Team-level integrations the agent expects to be configured (e.g. slack, github)."
        >
            {integrations.length === 0 ? (
                <EmptyState>No integrations declared.</EmptyState>
            ) : (
                <ul className="divide-y divide-border">
                    {integrations.map((name) => (
                        <li key={name} className="flex items-center justify-between px-3 py-2 text-xs">
                            <span className="font-medium">{name}</span>
                            <StatusBadge tone="muted">unknown</StatusBadge>
                        </li>
                    ))}
                </ul>
            )}
            <FollowupNote>Status check + punch-out to the team integrations page lands with the editor.</FollowupNote>
        </ConnectionCard>
    )
}

function McpsCard({ mcps }: { mcps: McpRef[] }): React.ReactElement {
    return (
        <ConnectionCard
            icon={<ServerIcon className="h-3.5 w-3.5" />}
            title="MCP servers"
            count={mcps.length}
            description="Runtime MCP endpoints the agent connects to at session start. Tools they expose route via the prefix `<id>__<name>`."
        >
            {mcps.length === 0 ? (
                <EmptyState>No MCP servers declared.</EmptyState>
            ) : (
                <ul className="divide-y divide-border">
                    {mcps.map((m, i) => (
                        <li key={i} className="space-y-1 px-3 py-2 text-xs">
                            {m.kind === 'agent' ? (
                                <>
                                    <div className="flex items-center justify-between">
                                        <span className="font-medium">Agent</span>
                                        <StatusBadge tone="info">in-platform</StatusBadge>
                                    </div>
                                    <code className="block font-mono text-muted-foreground">{m.slug}</code>
                                </>
                            ) : (
                                <>
                                    <div className="flex items-center justify-between">
                                        <span className="font-medium">External</span>
                                        <StatusBadge tone="muted">unknown</StatusBadge>
                                    </div>
                                    <code className="block truncate font-mono text-muted-foreground">{m.url}</code>
                                    {m.auth?.integration ? (
                                        <span className="text-muted-foreground">
                                            via integration <code className="font-mono">{m.auth.integration}</code>
                                        </span>
                                    ) : null}
                                </>
                            )}
                        </li>
                    ))}
                </ul>
            )}
            <FollowupNote>
                Live reachability + tool count is a follow-up; today this is a static view of the spec.
            </FollowupNote>
        </ConnectionCard>
    )
}

function ConnectionCard({
    icon,
    title,
    count,
    description,
    children,
}: {
    icon: React.ReactNode
    title: string
    count: number
    description: string
    children: React.ReactNode
}): React.ReactElement {
    return (
        <section className="overflow-hidden rounded-md border border-border bg-card">
            <header className="border-b border-border bg-muted/20 px-3 py-2">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <span className="text-muted-foreground">{icon}</span>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-foreground">{title}</h3>
                        <span className="text-[0.625rem] text-muted-foreground tabular-nums">{count}</span>
                    </div>
                </div>
                <p className="mt-1 text-[0.6875rem] text-muted-foreground">{description}</p>
            </header>
            {children}
        </section>
    )
}

function EmptyState({ children }: { children: React.ReactNode }): React.ReactElement {
    return <div className="px-3 py-4 text-xs text-muted-foreground">{children}</div>
}

function FollowupNote({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <p className="border-t border-border bg-muted/10 px-3 py-1.5 text-[0.625rem] italic text-muted-foreground/80">
            {children}
        </p>
    )
}

function StatusBadge({
    tone,
    children,
}: {
    tone: 'muted' | 'info' | 'success' | 'warning' | 'destructive'
    children: React.ReactNode
}): React.ReactElement {
    const cls =
        tone === 'success'
            ? 'border-success-foreground/30 bg-success/30 text-success-foreground'
            : tone === 'info'
              ? 'border-info-foreground/30 bg-info/30 text-info-foreground'
              : tone === 'warning'
                ? 'border-warning-foreground/30 bg-warning/30 text-warning-foreground'
                : tone === 'destructive'
                  ? 'border-destructive-foreground/30 bg-destructive/30 text-destructive-foreground'
                  : 'border-border bg-muted/40 text-muted-foreground'
    return (
        <span
            className={`inline-flex h-4 items-center rounded-full border px-1.5 text-[0.625rem] uppercase tracking-wide ${cls}`}
        >
            {children}
        </span>
    )
}
