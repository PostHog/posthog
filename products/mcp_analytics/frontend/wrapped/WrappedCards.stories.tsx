import './MCPWrapped.scss'

import { Meta, StoryObj } from '@storybook/react'

import type { MCPWrappedCardsApi } from '../generated/api.schemas'
import { ArchetypeCard } from './cards/ArchetypeCard'
import { IntroCard } from './cards/IntroCard'
import { ReliabilityCard } from './cards/ReliabilityCard'
import { RushHourCard } from './cards/RushHourCard'
import { ShareCard } from './cards/ShareCard'
import { SharesCard } from './cards/SharesCard'
import { SpeedCard } from './cards/SpeedCard'
import { ToolCallsCard } from './cards/ToolCallsCard'
import { TopToolsCard } from './cards/TopToolsCard'

const heat = Array.from({ length: 168 }, (_, index) => {
    const weekday = Math.floor(index / 24)
    const hour = index % 24
    const workday = weekday < 5 ? 1 : 0.35
    return Math.round(Math.min(100, 8 + 92 * workday * Math.exp(-(((hour - 15) / 4.2) ** 2))))
})

const CARDS: MCPWrappedCardsApi = {
    intro: { tracked_since: '2026-07', server_count: 2 },
    tool_calls: {
        total_calls: 4812655,
        months: [
            { month: '2026-07', calls: 210000 },
            { month: '2026-08', calls: 640000 },
            { month: '2026-09', calls: 980000 },
            { month: '2026-10', calls: 1520000 },
            { month: '2026-11', calls: 1462655 },
        ],
        growth_multiple: 2.3,
    },
    top_tools: {
        tools: [
            { tool: 'get_forecast', calls: 1540000 },
            { tool: 'search_locations', calls: 1120000 },
            { tool: 'get_history', calls: 702000 },
            { tool: 'create_alert', calls: 361000 },
            { tool: 'list_alerts', calls: 268000 },
        ],
    },
    apps: {
        shares: [
            { name: 'Claude Code', share: 0.48 },
            { name: 'Cursor', share: 0.24 },
            { name: 'ChatGPT', share: 0.16 },
            { name: 'Other', share: 0.12 },
        ],
    },
    labs: {
        shares: [
            { name: 'Anthropic', share: 0.58 },
            { name: 'OpenAI', share: 0.27 },
            { name: 'Google', share: 0.09 },
            { name: 'Open weights', share: 0.06 },
        ],
    },
    models: {
        shares: [
            { name: 'Claude Sonnet', share: 0.41 },
            { name: 'GPT-6', share: 0.22 },
            { name: 'Claude Opus', share: 0.17 },
            { name: 'Gemini', share: 0.09 },
            { name: 'Other', share: 0.11 },
        ],
    },
    rush_hour: { weekday: 2, hour: 15, timezone: 'Europe/Lisbon', heat, quiet_weekends: true, night_shift: false },
    reliability: { success_rate: 0.976, struggling_tool: { tool: 'create_alert', error_rate: 0.082 } },
    speed: {
        p95_duration_ms: 410,
        quickest_busy_tool: { tool: 'list_alerts', p95_duration_ms: 120 },
        slowest_tool: { tool: 'get_history', p95_duration_ms: 2400 },
    },
    archetype: { archetype: 'swiss_army_knife', evidence: 6 },
}

function AllCards(): JSX.Element {
    return (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4 p-4">
            <IntroCard card={CARDS.intro} projectName="Weather Co" year={2026} />
            <ToolCallsCard card={CARDS.tool_calls} />
            <TopToolsCard card={CARDS.top_tools} totalCalls={CARDS.tool_calls.total_calls} />
            {CARDS.apps && (
                <SharesCard
                    cardKey="apps"
                    card={CARDS.apps}
                    kicker="The AI apps calling your server"
                    headline={(leader, share) => `${leader} led with ${share}`}
                    otherLabel="All other apps"
                />
            )}
            {CARDS.labs && (
                <SharesCard
                    cardKey="labs"
                    card={CARDS.labs}
                    kicker="The AI labs behind the agents"
                    headline={(leader, share) => `${leader} models made ${share} of calls`}
                    otherLabel="Other labs"
                />
            )}
            {CARDS.models && (
                <SharesCard
                    cardKey="models"
                    card={CARDS.models}
                    kicker="The models doing the calling"
                    headline={(leader, share) => `${leader} led with ${share}`}
                    otherLabel="Other models"
                />
            )}
            {CARDS.rush_hour && <RushHourCard card={CARDS.rush_hour} />}
            <ReliabilityCard card={CARDS.reliability} />
            {CARDS.speed && <SpeedCard card={CARDS.speed} />}
            <ArchetypeCard card={CARDS.archetype} />
            <ShareCard cards={CARDS} projectName="Weather Co" year={2026} />
        </div>
    )
}

const meta: Meta<typeof AllCards> = {
    title: 'Scenes-App/MCP Analytics/Wrapped cards',
    component: AllCards,
    parameters: {
        layout: 'fullscreen',
        // Product-specific and still changing during rollout, so render-checked without a visual baseline.
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof AllCards>

export const Cards: Story = {}
