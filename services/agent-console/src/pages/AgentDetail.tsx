/**
 * Agent detail — read panel for one agent. The chat dock lives in the
 * app shell and gets its context from the route via dock-context.
 *
 * Three tabs:
 *   - **Overview** — landing summary (stats + recent activity + trigger
 *     synopsis).
 *   - **Configuration** — app-level settings (top) + revisions browser
 *     (master-detail: list of revisions on the left, the selected
 *     revision's spec + bundle on the right). Configuration always
 *     belongs to a revision; this layout makes that explicit.
 *   - **Sessions** — per-agent session list with filter chips.
 *
 * Tab state is internal; v0.1+ may promote to URL params for shareable
 * links. Inter-tab navigation: Overview cards have "Open config" /
 * "All sessions →" links that switch tabs.
 */

import { ChevronRightIcon, PlayIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    BundleFile,
} from '@posthog/agent-chat/fixtures'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { AgentOverview } from '@/components/AgentOverview'
import { ApplicationSettings } from '@/components/ApplicationSettings'
import { useFocusStore, type FocusTarget } from '@/components/focus-context'
import { RevisionsBrowser } from '@/components/RevisionsBrowser'
import { SessionsList } from '@/components/SessionsList'

type TabKey = 'overview' | 'configuration' | 'sessions'

export interface AgentDetailProps {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    /** Bundle files for the currently-displayed revision. v0.1 fetches per revision. */
    bundle: BundleFile[]
    stats: AgentStats
    sessions: ChatSession[]
    /** Click to start a playground session against this agent. */
    onTryAgent?: () => void
    onOpenSession?: (sessionId: string) => void
    /** Click handler for the "Agents" crumb. Wired to router.push in Next.js, story-local nav in Storybook. */
    onBackToList?: () => void
}

export function AgentDetail({
    agent,
    revisions,
    bundle,
    stats,
    sessions,
    onTryAgent,
    onOpenSession,
    onBackToList,
}: AgentDetailProps): React.ReactElement {
    // The Configuration tab's master-detail picker — default to the live revision.
    const sortedRevisions = useMemo(
        () => [...revisions].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
        [revisions]
    )
    const defaultRevisionId = agent.live_revision ?? sortedRevisions[0]?.id ?? null

    const liveRevision = revisions.find((r) => r.id === agent.live_revision) ?? null
    const referenceRevision = liveRevision ?? sortedRevisions[0] ?? null
    const recentSessions = useMemo(() => sessions.slice(0, 5), [sessions])

    /**
     * Focus integration — instead of mirroring `focus.target` into local
     * state via `useEffect` (which can race against the async script
     * runner), we *derive* the active tab + selected revision from
     * focus.target on render. User clicks update a separate `userTab` /
     * `userRevId`; their click clears the focus target so user choice
     * takes back over. Clean, race-free, no chained state updates.
     */
    const focus = useFocusStore()
    const [userTab, setUserTab] = useState<TabKey>('overview')
    const [userRevId, setUserRevId] = useState<string | null>(defaultRevisionId)

    const tab: TabKey = useMemo(() => deriveTab(focus.target) ?? userTab, [focus.target, userTab])
    const selectedRevId: string | null = useMemo(() => {
        if (focus.target?.kind === 'revision') {
            return focus.target.revisionId
        }
        return userRevId
    }, [focus.target, userRevId])

    const handleTabChange = (next: TabKey): void => {
        setUserTab(next)
        focus.clear()
    }
    const handleRevisionChange = (id: string): void => {
        setUserRevId(id)
        focus.clear()
    }

    const focusedBundlePath = focus.target?.kind === 'file' ? focus.target.path : null

    return (
        <div className="mx-auto max-w-5xl px-6 py-6">
            <Breadcrumb name={agent.name} onBackToList={onBackToList} />

            <header className="mt-3 flex items-start justify-between gap-4">
                <div className="min-w-0 space-y-1">
                    <h1 className="text-xl font-medium tracking-tight">{agent.name}</h1>
                    <p className="text-sm text-muted-foreground">{agent.description}</p>
                </div>
                <button
                    type="button"
                    onClick={() => onTryAgent?.()}
                    className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium transition-colors hover:bg-accent"
                >
                    <PlayIcon className="h-3 w-3" />
                    Try in playground
                </button>
            </header>

            <Tabs value={tab} onValueChange={(v) => handleTabChange(v as TabKey)} className="mt-5">
                <TabsList variant="line">
                    <TabsTrigger value="overview">Overview</TabsTrigger>
                    <TabsTrigger value="configuration">Configuration</TabsTrigger>
                    <TabsTrigger value="sessions">
                        Sessions
                        {sessions.length > 0 ? (
                            <span className="ml-1.5 text-[0.6875rem] text-muted-foreground">{sessions.length}</span>
                        ) : null}
                    </TabsTrigger>
                </TabsList>

                <TabsContent value="overview" className="mt-4">
                    <AgentOverview
                        agent={agent}
                        liveRevision={liveRevision}
                        stats={stats}
                        recentSessions={recentSessions}
                        onOpenSession={onOpenSession}
                        onOpenConfiguration={() => handleTabChange('configuration')}
                        onOpenSessions={() => handleTabChange('sessions')}
                    />
                </TabsContent>

                <TabsContent value="configuration" className="mt-4 space-y-6">
                    <Section title="Settings">
                        <ApplicationSettings agent={agent} referenceRevision={referenceRevision} />
                    </Section>

                    <Section
                        title="Revisions"
                        right={
                            revisions.length > 0 ? (
                                <span className="text-[0.6875rem] text-muted-foreground">{revisions.length} total</span>
                            ) : null
                        }
                    >
                        <RevisionsBrowser
                            agent={agent}
                            revisions={revisions}
                            bundle={bundle}
                            selectedRevisionId={selectedRevId}
                            onSelectRevision={handleRevisionChange}
                            focusedBundlePath={focusedBundlePath}
                            focusedBundleTick={focus.tick}
                        />
                    </Section>
                </TabsContent>

                <TabsContent value="sessions" className="mt-4">
                    <SessionsList sessions={sessions} onOpenSession={onOpenSession} />
                </TabsContent>
            </Tabs>
        </div>
    )
}

/* ── Helpers ────────────────────────────────────────────────────── */

function deriveTab(target: FocusTarget | null): TabKey | null {
    if (!target) {
        return null
    }
    switch (target.kind) {
        case 'tab':
            return target.tab
        case 'file':
        case 'spec_section':
        case 'revision':
            return 'configuration'
        case 'session':
            return 'sessions'
        default:
            return null
    }
}

/* ── Sub-components ─────────────────────────────────────────────── */

function Breadcrumb({ name, onBackToList }: { name: string; onBackToList?: () => void }): React.ReactElement {
    return (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {onBackToList ? (
                <button type="button" onClick={onBackToList} className="cursor-pointer hover:text-foreground">
                    Agents
                </button>
            ) : (
                <span>Agents</span>
            )}
            <ChevronRightIcon className="h-3 w-3" />
            <span className="text-foreground">{name}</span>
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
                <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
                {right ? <div>{right}</div> : null}
            </div>
            {children}
        </section>
    )
}
