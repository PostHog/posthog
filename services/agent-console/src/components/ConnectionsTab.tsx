/**
 * `<ConnectionsTab>` — app-level wiring view.
 *
 * "What does this agent need to operate?" — secrets, team integrations,
 * and runtime MCP servers. The lists come from the live revision's
 * spec; per-row status badges layer on real state where we have it
 * (`env_keys/` for secrets, placeholders elsewhere until those
 * endpoints land).
 *
 * Secrets are editable here: each row has a Set / Rotate button that
 * pops `<SecretEditDialog>`. The URL carries the dialog state
 * (`?edit_secret=KEY`), so the concierge agent can deep-link the user
 * directly to "set ANTHROPIC_KEY now". When the URL also has
 * `?callback_session=<id>`, a successful save dispatches an event the
 * dock's chat runner picks up to resume the waiting session.
 *
 * Integrations and MCPs are still read-only here — editing those is
 * the next phase.
 */

'use client'

import { AlertCircleIcon, KeyIcon, LinkIcon, PlusIcon, ServerIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Label,
} from '@posthog/quill'

import { useSessionTeamId } from '@/components/session-context'
import { clearEnvKey, listEnvKeys } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

import { ConfirmDialog } from './ConfirmDialog'
import { SecretEditDialog } from './SecretEditDialog'

interface ConnectionsTabProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    /** Currently-open secret editor key (driven by `?edit_secret=` in the URL). */
    editingSecret: string | null
    /** Optional chat session id to notify on save / clear. */
    callbackSessionId: string | null
    /** Open the secret editor for `key` (or close when `null`). */
    onChangeEditingSecret: (key: string | null) => void
}

import type { McpRef } from '@/types/mcp'

export function ConnectionsTab({
    agent,
    revisions,
    editingSecret,
    callbackSessionId,
    onChangeEditingSecret,
}: ConnectionsTabProps): React.ReactElement {
    const teamId = useSessionTeamId()!
    const liveRevision = revisions.find((r) => r.id === agent.live_revision) ?? null
    // If there's no live revision, fall back to the most recent draft so the
    // page isn't blank — surface the fact clearly in the header.
    const sortedRevs = [...revisions].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    )
    const reference = liveRevision ?? sortedRevs[0] ?? null

    // Live env_keys list — names only, no values. Refetched after every
    // dialog save / clear via the `bump` reload signal so set / unset
    // chips stay accurate without a full page reload.
    const [reload, setReload] = useState(0)
    const envKeysRes = useResource(
        () => listEnvKeys(teamId, agent.slug).catch(() => [] as string[]),
        [teamId, agent.slug, reload]
    )
    const setKeys = envKeysRes.data ?? []
    const bumpReload = (): void => setReload((n) => n + 1)

    if (!reference) {
        return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                No revisions yet — connections will appear once a revision is published.
            </div>
        )
    }

    const spec = reference.spec as Record<string, unknown>
    const declaredSecrets = Array.isArray(spec.secrets) ? (spec.secrets as string[]) : []
    const integrations = Array.isArray(spec.integrations) ? (spec.integrations as string[]) : []
    const mcps = Array.isArray(spec.mcps) ? (spec.mcps as McpRef[]) : []

    // Show declared secrets even when unset, plus any "extra" set keys
    // that the spec doesn't declare. Extras are flagged so the user
    // knows they're orphaned — the agent won't read them unless the
    // spec is updated.
    const declaredSet = new Set(declaredSecrets)
    const extraKeys = setKeys.filter((k) => !declaredSet.has(k)).sort()
    const isDeclaredOnSpec = editingSecret ? declaredSet.has(editingSecret) : true

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

            <SecretsCard
                agentSlug={agent.slug}
                teamId={teamId}
                declared={declaredSecrets}
                extras={extraKeys}
                setKeys={new Set(setKeys)}
                onEdit={onChangeEditingSecret}
                onMutated={bumpReload}
            />
            <IntegrationsCard integrations={integrations} />
            <McpsCard mcps={mcps} />

            <SecretEditDialog
                agentSlug={agent.slug}
                secret={editingSecret}
                callbackSessionId={callbackSessionId}
                isDeclaredOnSpec={isDeclaredOnSpec}
                onClose={() => onChangeEditingSecret(null)}
                onMutated={bumpReload}
            />
        </div>
    )
}

function SecretsCard({
    agentSlug,
    teamId,
    declared,
    extras,
    setKeys,
    onEdit,
    onMutated,
}: {
    agentSlug: string
    teamId: number
    declared: string[]
    /** Set keys not declared on the spec. Listed under a separate group. */
    extras: string[]
    setKeys: ReadonlySet<string>
    onEdit: (key: string | null) => void
    onMutated: () => void
}): React.ReactElement {
    const [adding, setAdding] = useState(false)
    // Two-step delete: click the trash icon to stage `deletingKey`, then
    // confirm in the dialog. Errors stay inline so the user can retry
    // without losing context.
    const [deletingKey, setDeletingKey] = useState<string | null>(null)
    const [deleting, setDeleting] = useState(false)
    const [deleteError, setDeleteError] = useState<string | null>(null)
    const total = declared.length + extras.length

    const closeDelete = (): void => {
        if (deleting) {
            return
        }
        setDeletingKey(null)
        setDeleteError(null)
    }

    const confirmDelete = async (): Promise<void> => {
        if (!deletingKey || deleting) {
            return
        }
        setDeleting(true)
        setDeleteError(null)
        try {
            await clearEnvKey(teamId, agentSlug, deletingKey)
            onMutated()
            setDeletingKey(null)
        } catch (err) {
            setDeleteError(err instanceof Error ? err.message : String(err))
        } finally {
            setDeleting(false)
        }
    }

    return (
        <>
            <ConnectionCard
                icon={<KeyIcon className="h-3.5 w-3.5" />}
                title="Secrets"
                count={total}
                description="Encrypted env values the agent decrypts at session start. Names are declared on the spec; values live on the application."
                action={
                    <button
                        type="button"
                        onClick={() => setAdding(true)}
                        className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-md border border-border bg-card px-2 text-[0.6875rem] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                        <PlusIcon className="h-3 w-3" />
                        Add custom
                    </button>
                }
            >
                {declared.length === 0 && extras.length === 0 ? (
                    <EmptyState>No secrets declared.</EmptyState>
                ) : (
                    <>
                        {declared.length > 0 ? (
                            <ul className="divide-y divide-border">
                                {declared.map((name) => (
                                    <SecretRow key={name} name={name} isSet={setKeys.has(name)} onEdit={onEdit} />
                                ))}
                            </ul>
                        ) : null}
                        {extras.length > 0 ? (
                            <>
                                <div className="border-t border-border bg-muted/10 px-3 py-1.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                                    Set but not on spec
                                </div>
                                <ul className="divide-y divide-border">
                                    {extras.map((name) => (
                                        <SecretRow
                                            key={name}
                                            name={name}
                                            isSet
                                            isOrphan
                                            onEdit={onEdit}
                                            onDelete={() => setDeletingKey(name)}
                                        />
                                    ))}
                                </ul>
                            </>
                        ) : null}
                    </>
                )}
                <FollowupNote>
                    Values are write-only — the API never returns them. Rotate by saving a new value; the agent picks it
                    up at next session start.
                </FollowupNote>
            </ConnectionCard>
            <AddCustomSecretDialog
                open={adding}
                onCancel={() => setAdding(false)}
                onConfirm={(name) => {
                    setAdding(false)
                    onEdit(name)
                }}
            />
            <ConfirmDialog
                open={deletingKey !== null}
                onOpenChange={(o) => {
                    if (!o) {
                        closeDelete()
                    }
                }}
                title="Delete secret"
                description={
                    <>
                        Delete <code className="font-mono">{deletingKey}</code>? It's set on the application but not
                        declared on the live spec, so no agent is reading it. This clears the encrypted value
                        immediately and can't be undone.
                    </>
                }
                confirmLabel="Delete"
                confirmVariant="destructive"
                running={deleting}
                error={deleteError}
                onConfirm={() => void confirmDelete()}
            />
        </>
    )
}

function SecretRow({
    name,
    isSet,
    isOrphan,
    onEdit,
    onDelete,
}: {
    name: string
    isSet: boolean
    isOrphan?: boolean
    onEdit: (key: string | null) => void
    /** When provided, renders a trash button that opens a confirm dialog. */
    onDelete?: () => void
}): React.ReactElement {
    return (
        <li className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
            <div className="flex min-w-0 items-center gap-2">
                <code className="truncate font-mono">{name}</code>
                {isOrphan ? <StatusBadge tone="warning">orphan</StatusBadge> : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
                <StatusBadge tone={isSet ? 'success' : 'muted'}>{isSet ? 'set' : 'unset'}</StatusBadge>
                <button
                    type="button"
                    onClick={() => onEdit(name)}
                    className="inline-flex h-6 cursor-pointer items-center rounded-md border border-border bg-card px-2 text-[0.6875rem] font-medium transition-colors hover:bg-accent"
                >
                    {isSet ? 'Rotate' : 'Set'}
                </button>
                {onDelete ? (
                    <button
                        type="button"
                        onClick={onDelete}
                        aria-label={`Delete secret ${name}`}
                        title={`Delete ${name}`}
                        className="inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-destructive/20 hover:text-destructive-foreground"
                    >
                        <Trash2Icon className="h-3 w-3" />
                    </button>
                ) : null}
            </div>
        </li>
    )
}

/**
 * Tiny intermediate dialog that captures a new key name before opening
 * the `<SecretEditDialog>`. Splitting these out keeps the editor focused
 * on a known key (it pre-fetches set/unset status) and makes "add a key
 * the spec doesn't declare" an explicit, separately auditable action.
 */
function AddCustomSecretDialog({
    open,
    onCancel,
    onConfirm,
}: {
    open: boolean
    onCancel: () => void
    onConfirm: (name: string) => void
}): React.ReactElement {
    const [name, setName] = useState('')
    const trimmed = name.trim()
    const valid = trimmed.length > 0 && /^[A-Za-z_][A-Za-z0-9_]*$/.test(trimmed)
    return (
        <Dialog
            open={open}
            onOpenChange={(o) => {
                if (!o) {
                    setName('')
                    onCancel()
                }
            }}
        >
            <DialogContent>
                <form
                    onSubmit={(e) => {
                        e.preventDefault()
                        if (valid) {
                            const next = trimmed
                            setName('')
                            onConfirm(next)
                        }
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>Add a custom secret</DialogTitle>
                        <DialogDescription className="text-xs">
                            Setting a value here doesn't add the key to the spec — the agent will only read it once the
                            spec lists it. Use this for ad-hoc rotations or to pre-seed before publishing.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody render={<div />} className="space-y-3 px-6 py-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="custom-secret-name" className="text-xs">
                                Key name
                            </Label>
                            <Input
                                id="custom-secret-name"
                                autoFocus
                                value={name}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                                    setName(e.currentTarget.value.toUpperCase())
                                }
                                placeholder="MY_API_KEY"
                                spellCheck={false}
                            />
                            {!valid && trimmed.length > 0 ? (
                                <p className="text-[0.6875rem] text-warning-foreground">
                                    Letters, numbers, underscore. Must start with a letter or underscore.
                                </p>
                            ) : null}
                        </div>
                    </DialogBody>
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => {
                                setName('')
                                onCancel()
                            }}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={!valid}>
                            Continue
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
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
                            <div className="flex items-center justify-between">
                                <span className="font-medium">{m.id}</span>
                                <StatusBadge tone="muted">unknown</StatusBadge>
                            </div>
                            <code className="block truncate font-mono text-muted-foreground">{m.url}</code>
                            {m.auth?.integration ? (
                                <span className="text-muted-foreground">
                                    via integration <code className="font-mono">{m.auth.integration}</code>
                                </span>
                            ) : null}
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
    action,
    children,
}: {
    icon: React.ReactNode
    title: string
    count: number
    description: string
    /** Optional right-aligned action — e.g. an "Add" button. */
    action?: React.ReactNode
    children: React.ReactNode
}): React.ReactElement {
    return (
        <section className="overflow-hidden rounded-md border border-border bg-card">
            <header className="border-b border-border bg-muted/20 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <span className="text-muted-foreground">{icon}</span>
                        <h3 className="text-xs font-medium uppercase tracking-wide text-foreground">{title}</h3>
                        <span className="text-[0.625rem] text-muted-foreground tabular-nums">{count}</span>
                    </div>
                    {action ? <div className="shrink-0">{action}</div> : null}
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
