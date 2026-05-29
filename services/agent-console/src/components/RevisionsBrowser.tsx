/**
 * `<RevisionsBrowser />` — master-detail view for an agent's revisions.
 *
 * Configuration always belongs to a revision; this component makes that
 * relationship visible.
 *
 *   ┌──────────────┬────────────────────────────────────┐
 *   │ ● live  01a  │  [Config — Structured / Raw]       │
 *   │ ◯ draft 02   │  [Bundle tree]                     │
 *   │ ◯ ready 03   │                                    │
 *   └──────────────┴────────────────────────────────────┘
 *
 * Left list: compact rows, live pinned at top. Click to select.
 * Right pane: ConfigPanel + BundleTree for the selected revision,
 * with the Structured/Raw spec toggle in the section header.
 *
 * On narrow screens (md and below), the columns stack — list above,
 * detail below.
 */

'use client'

import { useMemo, useState } from 'react'

import { JsonView } from '@posthog/agent-chat'
import type { AgentApplicationFixture, AgentRevisionFixture, BundleFile } from '@posthog/agent-chat/fixtures'

import { BundleTree } from './BundleTree'
import { ConfigPanel, KNOWN_SPEC_KEYS, UnstructuredFields } from './ConfigPanel'

type ConfigView = 'structured' | 'raw'

export interface RevisionsBrowserProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    /** Bundle files for the *currently-selected* revision. v0.1: fetched per revision. */
    bundle: BundleFile[]
    /** Controlled selection — parent owns the choice so deep links can pre-select. */
    selectedRevisionId: string | null
    onSelectRevision: (id: string) => void
    /** External signal to open a specific bundle file, forwarded to BundleTree. */
    focusedBundlePath?: string | null
    focusedBundleTick?: number
}

export function RevisionsBrowser({
    agent,
    revisions,
    bundle,
    selectedRevisionId,
    onSelectRevision,
    focusedBundlePath,
    focusedBundleTick,
}: RevisionsBrowserProps): React.ReactElement {
    const [configView, setConfigView] = useState<ConfigView>('structured')

    const sortedRevisions = useMemo(() => {
        const live = revisions.find((r) => r.id === agent.live_revision)
        const others = revisions
            .filter((r) => r.id !== agent.live_revision)
            .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        return live ? [live, ...others] : others
    }, [revisions, agent.live_revision])

    const selected = revisions.find((r) => r.id === selectedRevisionId) ?? sortedRevisions[0] ?? null

    if (sortedRevisions.length === 0) {
        return (
            <p className="rounded-md border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
                This agent has no revisions yet.
            </p>
        )
    }

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
            <ul
                className="divide-y divide-border overflow-hidden rounded-md border border-border bg-background"
                aria-label="Revisions"
            >
                {sortedRevisions.map((r) => (
                    <li key={r.id}>
                        <RevisionListItem
                            revision={r}
                            isLive={r.id === agent.live_revision}
                            isSelected={selected?.id === r.id}
                            onClick={() => onSelectRevision(r.id)}
                        />
                    </li>
                ))}
            </ul>

            <div className="min-w-0 space-y-4">
                {selected ? (
                    <>
                        <RevisionMetaRow revision={selected} isLive={selected.id === agent.live_revision} />

                        <Section title="Config" right={<ConfigViewToggle view={configView} onChange={setConfigView} />}>
                            {configView === 'structured' ? (
                                <>
                                    <ConfigPanel
                                        spec={selected.spec as Record<string, unknown>}
                                        entityKey={`revision-spec:${agent.id}:${selected.id}`}
                                    />
                                    <UnstructuredFields
                                        spec={selected.spec as Record<string, unknown>}
                                        knownKeys={KNOWN_SPEC_KEYS}
                                    />
                                </>
                            ) : (
                                <JsonView value={selected.spec} defaultView="yaml" expandToLevel={3} />
                            )}
                        </Section>

                        <Section title="Bundle">
                            <div className="h-[480px]">
                                <BundleTree
                                    files={bundle}
                                    focusedPath={focusedBundlePath ?? null}
                                    focusedPathTick={focusedBundleTick}
                                    applicationId={agent.id}
                                />
                            </div>
                        </Section>
                    </>
                ) : (
                    <EmptyDetail />
                )}
            </div>
        </div>
    )
}

/* ── Subcomponents ───────────────────────────────────────────────── */

function RevisionListItem({
    revision,
    isLive,
    isSelected,
    onClick,
}: {
    revision: AgentRevisionFixture
    isLive: boolean
    isSelected: boolean
    onClick: () => void
}): React.ReactElement {
    const tone = stateTone(revision.state, isLive)
    return (
        <button
            type="button"
            onClick={onClick}
            aria-current={isSelected ? 'true' : undefined}
            className={
                (isSelected
                    ? 'bg-accent text-foreground'
                    : 'text-muted-foreground hover:bg-accent/40 hover:text-foreground') +
                ' group flex w-full cursor-pointer items-start gap-2 px-3 py-2 text-left transition-colors focus-visible:bg-accent focus-visible:outline-none'
            }
        >
            <span className={`mt-1.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5 text-xs">
                    <span className="font-medium">{tone.label}</span>
                    <code className="truncate text-[0.6875rem] text-muted-foreground">{short(revision.id)}</code>
                </div>
                <div className="mt-0.5 text-[0.6875rem] text-muted-foreground">
                    {formatRelative(revision.updated_at)} · {revision.created_by.first_name}
                </div>
            </div>
        </button>
    )
}

function RevisionMetaRow({
    revision,
    isLive,
}: {
    revision: AgentRevisionFixture
    isLive: boolean
}): React.ReactElement {
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
                <span
                    className={`inline-flex h-1.5 w-1.5 rounded-full ${stateTone(revision.state, isLive).dotClass}`}
                    aria-hidden
                />
                <span className="font-medium text-foreground">{isLive ? 'live' : revision.state}</span>
            </span>
            <span>·</span>
            <code className="text-[0.6875rem]">{short(revision.id)}</code>
            {revision.bundle_sha256 ? (
                <>
                    <span>·</span>
                    <code className="text-[0.6875rem] text-muted-foreground/70">
                        {revision.bundle_sha256.split(':').at(-1)?.slice(0, 8)}
                    </code>
                </>
            ) : null}
            <span>·</span>
            <span>by {revision.created_by.first_name}</span>
            <span>·</span>
            <span>updated {formatRelative(revision.updated_at)}</span>
        </div>
    )
}

function Section({
    title,
    right,
    children,
}: {
    title: string
    right?: React.ReactNode
    children: React.ReactNode
}): React.ReactElement {
    return (
        <section className="space-y-3">
            <div className="flex h-7 items-end justify-between">
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
                {right ? <div>{right}</div> : null}
            </div>
            {children}
        </section>
    )
}

function ConfigViewToggle({
    view,
    onChange,
}: {
    view: ConfigView
    onChange: (next: ConfigView) => void
}): React.ReactElement {
    const options: ConfigView[] = ['structured', 'raw']
    return (
        <div
            className="inline-flex overflow-hidden rounded border border-border bg-background"
            role="group"
            aria-label="Config view"
        >
            {options.map((opt, i) => (
                <button
                    key={opt}
                    type="button"
                    onClick={() => onChange(opt)}
                    aria-pressed={view === opt}
                    className={
                        (view === opt
                            ? 'bg-accent text-foreground'
                            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground') +
                        ' cursor-pointer px-2 py-0.5 text-[0.6875rem] font-medium uppercase tracking-wide transition-colors' +
                        (i > 0 ? ' border-l border-border' : '')
                    }
                >
                    {opt}
                </button>
            ))}
        </div>
    )
}

function EmptyDetail(): React.ReactElement {
    return (
        <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
            Pick a revision to view its config and bundle.
        </div>
    )
}

function stateTone(state: AgentRevisionFixture['state'], isLive: boolean): { dotClass: string; label: string } {
    if (isLive) {
        return { dotClass: 'bg-success', label: 'live' }
    }
    switch (state) {
        case 'draft':
            return { dotClass: 'bg-warning', label: 'draft' }
        case 'ready':
            return { dotClass: 'bg-info', label: 'ready' }
        case 'archived':
            return { dotClass: 'bg-muted-foreground/40', label: 'archived' }
        case 'live':
            return { dotClass: 'bg-success', label: 'live' }
        default:
            return { dotClass: 'bg-muted-foreground/40', label: state }
    }
}

function short(id: string): string {
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
    if (diff < hour) {
        return `${Math.max(1, Math.floor(diff / minute))}m ago`
    }
    if (diff < day) {
        return `${Math.floor(diff / hour)}h ago`
    }
    return `${Math.floor(diff / day)}d ago`
}
