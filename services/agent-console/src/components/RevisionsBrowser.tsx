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

import { PlayIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import { JsonView } from '@posthog/agent-chat'
import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

import { useSessionTeamId } from '@/components/session-context'
import { ApiError, archiveRevision, freezeRevision, getBundle, promoteRevision } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

import { BundleTree } from './BundleTree'
import { ConfigPanel, KNOWN_SPEC_KEYS, UnstructuredFields } from './ConfigPanel'
import { ConfirmDialog } from './ConfirmDialog'

type ConfigView = 'structured' | 'raw'

export interface RevisionsBrowserProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    /** Controlled selection — parent owns the choice so deep links can pre-select. */
    selectedRevisionId: string | null
    onSelectRevision: (id: string) => void
    /** Highlighted spec section (driven by `?section=` in the URL). */
    highlightedSection?: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' | null
    /** Currently-open bundle file (driven by `?file=` in the URL). */
    focusedBundlePath?: string | null
    onSelectBundleFile?: (path: string) => void
    /** Refetch trigger after a successful lifecycle action. */
    onMutated?: () => void
    /**
     * Open the playground against a specific non-live revision via the
     * preview-proxy. Surfaced as a "Try draft" button on revisions
     * that have a chat trigger.
     */
    onTryDraft?: (revisionId: string) => void
}

type LifecycleAction = 'freeze' | 'promote' | 'archive'

interface PendingAction {
    action: LifecycleAction
    revision: AgentRevisionFixture
}

export function RevisionsBrowser({
    agent,
    revisions,
    selectedRevisionId,
    onSelectRevision,
    highlightedSection,
    focusedBundlePath,
    onSelectBundleFile,
    onMutated,
    onTryDraft,
}: RevisionsBrowserProps): React.ReactElement {
    const [configView, setConfigView] = useState<ConfigView>('structured')
    const [pending, setPending] = useState<PendingAction | null>(null)
    const [running, setRunning] = useState(false)
    const [actionError, setActionError] = useState<string | null>(null)

    const sortedRevisions = useMemo(() => {
        const live = revisions.find((r) => r.id === agent.live_revision)
        const others = revisions
            .filter((r) => r.id !== agent.live_revision)
            .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        return live ? [live, ...others] : others
    }, [revisions, agent.live_revision])

    const selected = revisions.find((r) => r.id === selectedRevisionId) ?? sortedRevisions[0] ?? null
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!

    const requestAction = (action: LifecycleAction, revision: AgentRevisionFixture): void => {
        setActionError(null)
        setPending({ action, revision })
    }
    const closeDialog = (): void => {
        if (running) {
            return
        }
        setPending(null)
        setActionError(null)
    }
    const runAction = async (): Promise<void> => {
        if (!pending) {
            return
        }
        setRunning(true)
        setActionError(null)
        const fn =
            pending.action === 'freeze'
                ? freezeRevision
                : pending.action === 'promote'
                  ? promoteRevision
                  : archiveRevision
        try {
            await fn(teamId, agent.slug, pending.revision.id)
            setPending(null)
            onMutated?.()
        } catch (err) {
            const msg = err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err)
            setActionError(msg)
        } finally {
            setRunning(false)
        }
    }

    // Bundle is per-revision — fetch lazily for whichever revision is selected.
    const bundleRes = useResource(
        () => (selected ? getBundle(teamId, agent.slug, selected.id) : Promise.resolve([])),
        [teamId, agent.slug, selected?.id ?? '']
    )
    const bundle = bundleRes.data ?? []
    const bundleLoading = bundleRes.loading
    const bundleError = bundleRes.error

    if (sortedRevisions.length === 0) {
        return (
            <p className="rounded-md border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
                This agent has no revisions yet.
            </p>
        )
    }

    return (
        <>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
                <ul
                    className="divide-y divide-border overflow-hidden rounded-md border border-border bg-card"
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
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <RevisionMetaRow revision={selected} isLive={selected.id === agent.live_revision} />
                                <RevisionActions
                                    revision={selected}
                                    isLive={selected.id === agent.live_revision}
                                    hasLiveRevision={!!agent.live_revision}
                                    onAction={(action) => requestAction(action, selected)}
                                    onTryDraft={onTryDraft ? () => onTryDraft(selected.id) : undefined}
                                />
                            </div>

                            <Section
                                title="Config"
                                right={<ConfigViewToggle view={configView} onChange={setConfigView} />}
                            >
                                {configView === 'structured' ? (
                                    <>
                                        <ConfigPanel
                                            spec={selected.spec as Record<string, unknown>}
                                            highlightedSection={highlightedSection}
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
                                    {bundleError ? (
                                        <div className="flex h-full items-center justify-center rounded-md border border-dashed border-border text-sm text-destructive-foreground">
                                            Failed to load bundle: {bundleError.message}
                                        </div>
                                    ) : bundleLoading ? (
                                        <div className="flex h-full items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
                                            Loading bundle…
                                        </div>
                                    ) : (
                                        <BundleTree
                                            files={bundle}
                                            selectedPath={focusedBundlePath ?? null}
                                            onSelectPath={onSelectBundleFile}
                                        />
                                    )}
                                </div>
                            </Section>
                        </>
                    ) : (
                        <EmptyDetail />
                    )}
                </div>
            </div>
            {pending ? (
                <ConfirmDialog
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            closeDialog()
                        }
                    }}
                    title={dialogCopy(pending, agent).title}
                    description={dialogCopy(pending, agent).description}
                    confirmLabel={dialogCopy(pending, agent).confirmLabel}
                    confirmVariant={pending.action === 'archive' ? 'destructive' : 'default'}
                    running={running}
                    error={actionError}
                    onConfirm={runAction}
                />
            ) : null}
        </>
    )
}

function dialogCopy(
    pending: PendingAction,
    agent: AgentApplicationFixture
): { title: string; description: React.ReactNode; confirmLabel: string } {
    const id = short(pending.revision.id)
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

function RevisionActions({
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

/** Whether a revision's spec declares a `chat` trigger. */
function hasChatTrigger(spec: Record<string, unknown>): boolean {
    const triggers = (spec as { triggers?: unknown }).triggers
    if (!Array.isArray(triggers)) {
        return false
    }
    return triggers.some((t) => typeof t === 'object' && t !== null && (t as { type?: unknown }).type === 'chat')
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
            className="inline-flex overflow-hidden rounded border border-border bg-card"
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
