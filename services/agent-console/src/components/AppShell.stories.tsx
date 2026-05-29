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
import { AgentDetailClient } from '../../app/agents/[slug]/agent-detail-client'
import { SessionDetailClient } from '../../app/agents/[slug]/sessions/[sessionId]/session-detail-client'
import { AppShell } from './AppShell'

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
            <AgentDetailClient slug="weekly-digest" />
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
            <AgentDetailClient slug="release-concierge" />
        </AppShell>
    ),
}

/** Session detail uses one of the session fixtures. */
export const SessionDetail: Story = {
    render: () => (
        <AppShell>
            <SessionDetailClient slug="weekly-digest" sessionId="01998a01-2222-7000-8000-0000000007d2" />
        </AppShell>
    ),
}
