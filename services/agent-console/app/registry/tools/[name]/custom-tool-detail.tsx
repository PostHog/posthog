'use client'

import { ChevronRightIcon, CopyIcon, HistoryIcon, PencilIcon, Trash2Icon } from 'lucide-react'
import Link from 'next/link'

import { JsonView } from '@posthog/agent-chat'

import type { CustomToolTemplateDetail } from '@/lib/registryFixtures'

export function CustomToolDetail({ tool }: { tool: CustomToolTemplateDetail }): React.ReactElement {
    const canonical = tool.name.startsWith('@posthog/')
    return (
        <div className="mx-auto max-w-5xl space-y-4 px-6 py-6">
            <Breadcrumb name={tool.name} />
            <header className="space-y-1.5">
                <div className="flex items-center gap-2">
                    <code className="font-mono text-sm">{tool.name}</code>
                    <span className="text-[0.6875rem] text-muted-foreground">v{tool.version}</span>
                    <Chip tone={canonical ? 'info' : 'muted'}>{canonical ? 'canonical' : 'team'}</Chip>
                </div>
                <p className="text-sm text-foreground/90">{tool.description}</p>
                <div className="flex items-center justify-between pt-1">
                    <p className="text-[0.6875rem] text-muted-foreground/80">
                        {tool.created_by ? `by ${tool.created_by}` : 'PostHog-canonical'} · updated{' '}
                        {formatRelative(tool.updated_at)} · used by {tool.usage_count} agent
                        {tool.usage_count === 1 ? '' : 's'}
                    </p>
                    <div className="flex items-center gap-1.5">
                        <ActionButton icon={<PencilIcon className="h-3 w-3" />} label="Edit" disabled />
                        <ActionButton icon={<CopyIcon className="h-3 w-3" />} label="Duplicate" disabled />
                        <ActionButton
                            icon={<Trash2Icon className="h-3 w-3" />}
                            label="Archive"
                            disabled
                            tone="destructive"
                        />
                    </div>
                </div>
                <p className="text-[0.6875rem] italic text-muted-foreground/70">
                    Inline source editing lands in v0.1; v0 ships a read-only source viewer + edits via the concierge.
                </p>
            </header>

            {tool.requires_secrets.length > 0 ? (
                <Section title="Requires secrets">
                    <div className="flex flex-wrap gap-1.5 text-xs">
                        {tool.requires_secrets.map((s) => (
                            <Chip key={s} tone="muted">
                                {s}
                            </Chip>
                        ))}
                    </div>
                </Section>
            ) : null}

            <Section title="Source">
                <pre className="overflow-auto rounded-md border border-border bg-muted/20 p-3 font-mono text-[0.75rem] leading-relaxed">
                    {tool.source}
                </pre>
            </Section>

            <Section title="Arguments">
                <div className="rounded-md border border-border bg-muted/20 p-3">
                    <JsonView value={tool.args_schema} expandToLevel={2} />
                </div>
            </Section>

            {tool.returns_schema ? (
                <Section title="Returns">
                    <div className="rounded-md border border-border bg-muted/20 p-3">
                        <JsonView value={tool.returns_schema} expandToLevel={1} />
                    </div>
                </Section>
            ) : null}

            <UsagesPanel usages={tool.usages} />
            <HistoryPanel history={tool.history} currentVersion={tool.version} />
        </div>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
    return (
        <section className="space-y-2">
            <h2 className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
            {children}
        </section>
    )
}

function UsagesPanel({ usages }: { usages: CustomToolTemplateDetail['usages'] }): React.ReactElement {
    return (
        <section className="overflow-hidden rounded-md border border-border bg-card">
            <header className="flex items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2">
                <h3 className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">Used by</h3>
                <span className="text-[0.625rem] text-muted-foreground/80">
                    {usages.length} agent{usages.length === 1 ? '' : 's'}
                </span>
            </header>
            {usages.length === 0 ? (
                <div className="px-3 py-3 text-xs text-muted-foreground">No agents pin this tool yet.</div>
            ) : (
                <ul className="divide-y divide-border">
                    {usages.map((u) => (
                        <li
                            key={`${u.agent_slug}:${u.revision_short_id}`}
                            className="flex items-center justify-between px-3 py-2 text-xs"
                        >
                            <Link href={`/agents/${u.agent_slug}`} className="flex items-center gap-2 hover:underline">
                                <span className="font-medium">{u.agent_name}</span>
                                <code className="text-[0.6875rem] text-muted-foreground">{u.revision_short_id}</code>
                            </Link>
                            <span className="text-[0.6875rem] text-muted-foreground">pinned v{u.pinned_version}</span>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    )
}

function HistoryPanel({
    history,
    currentVersion,
}: {
    history: CustomToolTemplateDetail['history']
    currentVersion: number
}): React.ReactElement {
    if (history.length === 0) {
        return <></>
    }
    return (
        <section className="overflow-hidden rounded-md border border-border bg-card">
            <header className="flex items-center gap-2 border-b border-border bg-muted/30 px-3 py-2">
                <HistoryIcon className="h-3 w-3 text-muted-foreground" />
                <h3 className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">
                    Version history
                </h3>
            </header>
            <ul className="divide-y divide-border">
                <li className="flex items-center justify-between px-3 py-2 text-xs">
                    <span className="font-medium">v{currentVersion}</span>
                    <span className="text-[0.6875rem] text-muted-foreground">current</span>
                </li>
                {history.map((h) => (
                    <li key={h.version} className="flex items-center justify-between px-3 py-2 text-xs">
                        <span>
                            <span className="font-medium">v{h.version}</span>
                            {h.note ? <span className="text-muted-foreground"> · {h.note}</span> : null}
                        </span>
                        <span className="text-[0.6875rem] text-muted-foreground">
                            {formatRelative(h.updated_at)}
                            {h.created_by ? ` · ${h.created_by}` : ''}
                        </span>
                    </li>
                ))}
            </ul>
        </section>
    )
}

function ActionButton({
    icon,
    label,
    disabled,
    tone = 'default',
}: {
    icon: React.ReactNode
    label: string
    disabled?: boolean
    tone?: 'default' | 'destructive'
}): React.ReactElement {
    return (
        <button
            type="button"
            disabled={disabled}
            className={
                'inline-flex h-6 cursor-pointer items-center gap-1 rounded border px-2 text-[0.6875rem] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ' +
                (tone === 'destructive'
                    ? 'border-destructive-foreground/40 text-destructive-foreground hover:bg-destructive/10'
                    : 'border-border bg-card hover:bg-accent')
            }
        >
            {icon}
            {label}
        </button>
    )
}

function Chip({ tone, children }: { tone: 'muted' | 'info'; children: React.ReactNode }): React.ReactElement {
    const cls =
        tone === 'info'
            ? 'border-info-foreground/30 bg-info/30 text-info-foreground'
            : 'border-border bg-muted/40 text-muted-foreground'
    return (
        <span
            className={`inline-flex h-4 items-center rounded-full border px-1.5 text-[0.625rem] uppercase tracking-wide ${cls}`}
        >
            {children}
        </span>
    )
}

function Breadcrumb({ name }: { name: string }): React.ReactElement {
    return (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Link href="/registry" className="cursor-pointer hover:text-foreground">
                Tools &amp; skills
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <Link href="/registry" className="cursor-pointer hover:text-foreground">
                Custom tools
            </Link>
            <ChevronRightIcon className="h-3 w-3" />
            <code className="text-foreground">{name}</code>
        </div>
    )
}

function formatRelative(iso: string): string {
    const ts = new Date(iso).getTime()
    if (!ts) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - ts)
    const day = 24 * 60 * 60 * 1000
    if (diff < day) {
        return 'today'
    }
    const days = Math.floor(diff / day)
    if (days < 30) {
        return `${days}d ago`
    }
    const months = Math.floor(days / 30)
    return `${months}mo ago`
}
