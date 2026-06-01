/**
 * Whole-shell stories — render the real `<AppShell>` against a real
 * `<AgentsListClient />` / `<AgentDetailClient />` with MSW serving
 * the API surface (see `.storybook/mocks/handlers.ts`) and a vite-
 * aliased stub for `next/navigation` (router calls become console.log
 * no-ops).
 *
 * This is the closest Storybook gets to the running console — useful
 * for design review and to catch any regression in the cross-component
 * composition (sidebar tooltips, session gate, dock layout, focus
 * mode toggle).
 */

import type { Meta, StoryObj } from '@storybook/react'

import { AgentsListClient } from '../../app/agents-list-client'
import { OverviewSegment } from '../../app/agents/[slug]/overview-client'
import { AgentProvider } from './agent-context'
import { AgentLayout } from './AgentLayout'
import { AppShell } from './AppShell'
import { AgentDetailSkeleton } from './PageSkeletons'

/**
 * Mounts the new route-segment composition inside Storybook — provider
 * (fetches the agent + revisions) → layout (shared chrome) → segment
 * body. Mirrors what `app/agents/[slug]/layout.tsx` does in the
 * production app; the segment content is whatever the route's
 * `page.tsx` would render (overview by default in these stories).
 */
function AgentDetailSurface({ slug }: { slug: string }): React.ReactElement {
    return (
        <AgentProvider
            slug={slug}
            fallback={<AgentDetailSkeleton />}
            notFoundFallback={<div className="px-6 py-6 text-sm text-muted-foreground">Agent not found.</div>}
            errorFallback={(err) => (
                <div className="px-6 py-6 text-sm text-destructive-foreground">Failed to load: {err.message}</div>
            )}
        >
            <AgentLayout>
                <OverviewSegment />
            </AgentLayout>
        </AgentProvider>
    )
}

const meta: Meta<typeof AppShell> = {
    title: 'Agent console/Shell (full surface)',
    component: AppShell,
    parameters: { layout: 'fullscreen' },
}

export default meta
type Story = StoryObj<typeof AppShell>

export const AgentsList: Story = {
    render: () => (
        <AppShell>
            <AgentsListClient />
        </AppShell>
    ),
}

/** Renders the agent detail for the `weekly-digest` fixture agent. */
export const AgentDetail_WeeklyDigest: Story = {
    render: () => (
        <AppShell>
            <AgentDetailSurface slug="weekly-digest" />
        </AppShell>
    ),
}

/** Configuration tab — selected via URL search-param convention.
 *  Storybook's `useSearchParams` stub returns empty, so to show a
 *  non-default tab we'd need a custom router (not worth it yet);
 *  flip tabs via the in-page tab list. */
export const AgentDetail_ReleaseConcierge: Story = {
    render: () => (
        <AppShell>
            <AgentDetailSurface slug="release-concierge" />
        </AppShell>
    ),
}

/**
 * Session detail now lives inline under the agent detail's sessions tab —
 * see the dedicated `Pages/Agent Detail / SessionsWithSelection` story
 * for the focused view. This shell-level story stays as the agent-list
 * landing.
 */
