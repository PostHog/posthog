/**
 * `<RevisionBar />` — the thin header strip above the config explorer.
 *
 * It's the one piece of the old `RevisionsBrowser` that the explorer
 * doesn't absorb: pick which revision you're looking at, and run the
 * lifecycle actions on it (freeze / promote / archive / try-draft).
 * Everything below it — the whole spec + bundle — is the explorer.
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │ ● live · 01a2b3c4 ▾   sha 9f… · by Ben      [Freeze] [Try]  │
 *   └────────────────────────────────────────────────────────────┘
 *
 * Presentational: it emits `onSelectRevision` / `onAction` / `onTryDraft`
 * and holds no API state, so it drops straight into Storybook. The host
 * (`AgentConfigView`) wires the lifecycle confirm + API calls.
 */

'use client'

import { ChevronDownIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'
import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import {
    DEFAULT_STATE_FILTERS,
    formatRelative,
    type LifecycleAction,
    RevisionActions,
    RevisionPicker,
    shortId,
    type StateFilter,
    stateTone,
} from './RevisionsBrowser'

export interface RevisionBarProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    selectedRevisionId: string | null
    onSelectRevision: (id: string) => void
    /** Request a lifecycle action — the host shows the confirm + runs it. */
    onAction: (action: LifecycleAction, revision: AgentRevisionFixture) => void
    /** Open the playground against a non-live revision via the preview-proxy. */
    onTryDraft?: (revisionId: string) => void
}

export function RevisionBar({
    agent,
    revisions,
    selectedRevisionId,
    onSelectRevision,
    onAction,
    onTryDraft,
}: RevisionBarProps): React.ReactElement | null {
    const [query, setQuery] = useState('')
    const [activeFilters, setActiveFilters] = useState<Set<StateFilter>>(() => new Set(DEFAULT_STATE_FILTERS))
    const [pickerOpen, setPickerOpen] = useState(false)

    const sortedRevisions = useMemo(() => {
        const live = revisions.find((r) => r.id === agent.live_revision)
        const others = revisions
            .filter((r) => r.id !== agent.live_revision)
            .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        return live ? [live, ...others] : others
    }, [revisions, agent.live_revision])

    const visibleRevisions = useMemo(() => {
        const q = query.trim().toLowerCase()
        return sortedRevisions.filter((r) => {
            const isLive = r.id === agent.live_revision
            const state: StateFilter = isLive ? 'live' : (r.state as StateFilter)
            if (!activeFilters.has(state)) {
                return false
            }
            if (!q) {
                return true
            }
            const hay = [r.id, r.bundle_sha256 ?? '', r.created_by?.first_name ?? '', r.created_by?.email ?? '']
                .join(' ')
                .toLowerCase()
            return hay.includes(q)
        })
    }, [sortedRevisions, activeFilters, query, agent.live_revision])

    const selected = revisions.find((r) => r.id === selectedRevisionId) ?? sortedRevisions[0] ?? null

    if (!selected) {
        return null
    }

    const isLive = selected.id === agent.live_revision
    const toggleFilter = (k: StateFilter): void => {
        setActiveFilters((prev) => {
            const next = new Set(prev)
            if (next.has(k)) {
                next.delete(k)
            } else {
                next.add(k)
            }
            return next
        })
    }
    const onPick = (id: string): void => {
        onSelectRevision(id)
        setPickerOpen(false)
    }
    const sha = selected.bundle_sha256?.split(':').at(-1)?.slice(0, 8)

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md border border-border bg-card px-2 py-1.5">
            <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
                <PopoverTrigger
                    render={
                        <button
                            type="button"
                            className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-md border border-border bg-background px-3 text-xs font-medium hover:bg-accent"
                        />
                    }
                >
                    <span className="inline-flex items-center gap-1.5">
                        <span
                            className={`inline-flex h-1.5 w-1.5 rounded-full ${stateTone(selected.state, isLive).dotClass}`}
                            aria-hidden
                        />
                        <span className="font-medium text-foreground">{isLive ? 'live' : selected.state}</span>
                    </span>
                    <span className="text-muted-foreground/60">·</span>
                    <code className="text-[0.6875rem] text-muted-foreground">{shortId(selected.id)}</code>
                    <ChevronDownIcon className="h-3 w-3 text-muted-foreground" />
                </PopoverTrigger>
                <PopoverContent side="bottom" align="start" sideOffset={6} className="w-80 p-0">
                    <RevisionPicker
                        agent={agent}
                        visibleRevisions={visibleRevisions}
                        totalCount={sortedRevisions.length}
                        selectedId={selected.id}
                        query={query}
                        onQueryChange={setQuery}
                        activeFilters={activeFilters}
                        onToggleFilter={toggleFilter}
                        onPick={onPick}
                    />
                </PopoverContent>
            </Popover>

            <div className="hidden flex-wrap items-center gap-x-2 text-[0.6875rem] text-muted-foreground sm:flex">
                {sha ? (
                    <span>
                        sha <code className="text-[0.6875rem]">{sha}</code>
                    </span>
                ) : null}
                <span>by {selected.created_by?.first_name ?? 'Unknown user'}</span>
                <span>updated {formatRelative(selected.updated_at)}</span>
            </div>

            <div className="ml-auto">
                <RevisionActions
                    revision={selected}
                    isLive={isLive}
                    hasLiveRevision={!!agent.live_revision}
                    onAction={(action) => onAction(action, selected)}
                    onTryDraft={onTryDraft ? () => onTryDraft(selected.id) : undefined}
                />
            </div>
        </div>
    )
}
