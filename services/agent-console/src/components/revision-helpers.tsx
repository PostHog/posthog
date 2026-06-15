/**
 * Shared revision helpers — state tones, id formatting, the lifecycle-action
 * dialog copy, and the popover-mounted revision picker / action buttons.
 *
 * These were extracted from the old `RevisionsBrowser` split view (now removed,
 * replaced by `AgentConfigView` + `AgentConfigExplorer`). `RevisionBar` and
 * `AgentConfigView` are the live consumers.
 */

'use client'

import { PlayIcon, SearchIcon } from 'lucide-react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

/** State chip values — multi-select; archived is off by default. */
const STATE_FILTERS = ['live', 'ready', 'draft', 'archived'] as const
export type StateFilter = (typeof STATE_FILTERS)[number]
export const DEFAULT_STATE_FILTERS: ReadonlySet<StateFilter> = new Set(['live', 'ready', 'draft'])

export type LifecycleAction = 'freeze' | 'promote' | 'archive'

interface PendingAction {
    action: LifecycleAction
    revision: AgentRevisionFixture
}

export function shortId(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

export function stateTone(state: AgentRevisionFixture['state'], isLive: boolean): { dotClass: string; label: string } {
    // Saturated `-foreground` variants for visibility on the light surface.
    if (isLive) {
        return { dotClass: 'bg-success-foreground', label: 'live' }
    }
    switch (state) {
        case 'draft':
            return { dotClass: 'bg-warning-foreground', label: 'draft' }
        case 'ready':
            return { dotClass: 'bg-info-foreground', label: 'ready' }
        case 'archived':
            return { dotClass: 'bg-muted-foreground/40', label: 'archived' }
        case 'live':
            return { dotClass: 'bg-success-foreground', label: 'live' }
        default:
            return { dotClass: 'bg-muted-foreground/40', label: state }
    }
}

export function formatRelative(iso: string): string {
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

export function dialogCopy(
    pending: PendingAction,
    agent: AgentApplicationFixture
): { title: string; description: React.ReactNode; confirmLabel: string } {
    const id = shortId(pending.revision.id)
    if (pending.action === 'freeze') {
        return {
            title: `Freeze revision ${id}`,
            description: (
                <>
                    Stamps the bundle sha256 and locks the spec. The revision moves from <strong>draft</strong> to{' '}
                    <strong>ready</strong> and becomes immutable. Required before promoting to live.
                </>
            ),
            confirmLabel: 'Freeze',
        }
    }
    if (pending.action === 'promote') {
        const replacing = agent.live_revision && agent.live_revision !== pending.revision.id
        return {
            title: `Promote ${id} to live`,
            description: replacing ? (
                <>
                    The current live revision will be demoted to <strong>archived</strong> and traffic will switch to{' '}
                    <code>{id}</code> immediately.
                </>
            ) : (
                <>
                    This will become the live revision for <strong>{agent.name}</strong>. The playground and any
                    configured triggers will start serving from it immediately.
                </>
            ),
            confirmLabel: 'Promote to live',
        }
    }
    return {
        title: `Archive revision ${id}`,
        description:
            pending.revision.id === agent.live_revision ? (
                <>
                    This is the currently live revision — archiving it will leave the agent with no deployable version
                    until another revision is promoted.
                </>
            ) : (
                <>This revision will be hidden from the default list and can no longer be promoted.</>
            ),
        confirmLabel: 'Archive',
    }
}

/** Whether a revision's spec declares a `chat` trigger. */
function hasChatTrigger(spec: Record<string, unknown>): boolean {
    const triggers = (spec as { triggers?: unknown }).triggers
    if (!Array.isArray(triggers)) {
        return false
    }
    return triggers.some((t) => typeof t === 'object' && t !== null && (t as { type?: unknown }).type === 'chat')
}

export function RevisionActions({
    revision,
    isLive,
    hasLiveRevision,
    onAction,
    onTryDraft,
}: {
    revision: AgentRevisionFixture
    isLive: boolean
    hasLiveRevision: boolean
    onAction: (action: LifecycleAction) => void
    /** Open the playground against this revision via the preview-proxy. */
    onTryDraft?: () => void
}): React.ReactElement | null {
    const buttons: { label: string; action: LifecycleAction; tone: 'default' | 'destructive' }[] = []

    if (revision.state === 'draft') {
        buttons.push({ label: 'Freeze', action: 'freeze', tone: 'default' })
    }
    if (revision.state === 'ready') {
        buttons.push({ label: 'Promote to live', action: 'promote', tone: 'default' })
    }
    // Don't offer archive on a live revision when there's no replacement
    // ready — the Django side would 400 (no deployable version left would
    // technically be allowed, but the UX is confusing). Surface it only
    // when it's safe to archive in one click.
    if (revision.state !== 'archived' && !(isLive && hasLiveRevision)) {
        buttons.push({ label: 'Archive', action: 'archive', tone: 'destructive' })
    }

    // "Try draft" goes through the preview-proxy — only meaningful for
    // non-live, non-archived revisions whose spec has a chat trigger.
    const showTryDraft = !isLive && revision.state !== 'archived' && hasChatTrigger(revision.spec) && !!onTryDraft

    if (buttons.length === 0 && !showTryDraft) {
        return null
    }

    return (
        <div className="flex shrink-0 gap-1.5">
            {showTryDraft ? (
                <button
                    type="button"
                    onClick={() => onTryDraft?.()}
                    title="Open the playground against this revision via the preview-proxy"
                    className="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2.5 text-[0.6875rem] font-medium text-foreground transition-colors hover:bg-primary/20"
                >
                    <PlayIcon className="h-3 w-3" />
                    Try draft
                </button>
            ) : null}
            {buttons.map((b) => (
                <button
                    key={b.action}
                    type="button"
                    onClick={() => onAction(b.action)}
                    className={
                        'inline-flex h-7 cursor-pointer items-center rounded-md border px-2.5 text-[0.6875rem] font-medium transition-colors ' +
                        (b.tone === 'destructive'
                            ? 'border-destructive-foreground/40 text-destructive-foreground hover:bg-destructive/40'
                            : 'border-border bg-card hover:bg-accent')
                    }
                >
                    {b.label}
                </button>
            ))}
        </div>
    )
}

export function RevisionPicker({
    agent,
    visibleRevisions,
    totalCount,
    selectedId,
    query,
    onQueryChange,
    activeFilters,
    onToggleFilter,
    onPick,
}: {
    agent: AgentApplicationFixture
    visibleRevisions: AgentRevisionFixture[]
    totalCount: number
    selectedId: string | null
    query: string
    onQueryChange: (q: string) => void
    activeFilters: Set<StateFilter>
    onToggleFilter: (f: StateFilter) => void
    onPick: (id: string) => void
}): React.ReactElement {
    return (
        <div className="flex max-h-[70vh] flex-col overflow-hidden">
            <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2">
                <span className="text-[0.6875rem] font-medium uppercase tracking-wide text-muted-foreground">
                    Revisions
                </span>
                <span className="text-[0.625rem] text-muted-foreground/70 tabular-nums">
                    {visibleRevisions.length} / {totalCount}
                </span>
            </div>
            <div className="space-y-2 border-b border-border bg-muted/10 px-2 py-2">
                <div className="relative">
                    <SearchIcon className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
                    <input
                        type="search"
                        value={query}
                        onChange={(e) => onQueryChange(e.currentTarget.value)}
                        placeholder="Search id, sha, author…"
                        autoFocus
                        className="h-7 w-full rounded border border-input bg-background pl-7 pr-2 text-xs"
                    />
                </div>
                <div className="flex flex-wrap gap-1">
                    {STATE_FILTERS.map((f) => {
                        const active = activeFilters.has(f)
                        return (
                            <button
                                key={f}
                                type="button"
                                onClick={() => onToggleFilter(f)}
                                aria-pressed={active}
                                className={
                                    'inline-flex h-5 cursor-pointer items-center gap-1 rounded-full border px-2 text-[0.625rem] uppercase tracking-wide transition-colors ' +
                                    (active
                                        ? 'border-foreground/20 bg-accent text-foreground'
                                        : 'border-border text-muted-foreground hover:bg-accent/40 hover:text-foreground')
                                }
                            >
                                <span
                                    className={`inline-flex h-1 w-1 rounded-full ${stateTone(f, f === 'live').dotClass}`}
                                    aria-hidden
                                />
                                {f}
                            </button>
                        )
                    })}
                </div>
            </div>
            <ul className="flex-1 divide-y divide-border overflow-auto" aria-label="Revisions">
                {visibleRevisions.length === 0 ? (
                    <li className="px-3 py-3 text-xs text-muted-foreground">No matching revisions.</li>
                ) : (
                    visibleRevisions.map((r) => (
                        <li key={r.id}>
                            <RevisionListItem
                                revision={r}
                                isLive={r.id === agent.live_revision}
                                isSelected={selectedId === r.id}
                                onClick={() => onPick(r.id)}
                            />
                        </li>
                    ))
                )}
            </ul>
        </div>
    )
}

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
                    <code className="truncate text-[0.6875rem] text-muted-foreground">{shortId(revision.id)}</code>
                </div>
                <div className="mt-0.5 text-[0.6875rem] text-muted-foreground">
                    {formatRelative(revision.updated_at)} · {revision.created_by?.first_name ?? 'Unknown user'}
                </div>
            </div>
        </button>
    )
}
