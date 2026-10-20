import type { Meta, StoryObj } from '@storybook/react'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { McpDateFilter } from './McpDateFilter'
import { McpSharedFilters } from './McpSharedFilters'

const FILTERS: AnyPropertyFilter[] = [
    { key: '$mcp_client_name', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: 'Claude' },
    { key: '$mcp_tool_name', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: 'search' },
]

const meta: Meta<typeof McpSharedFilters> = {
    title: 'Products/MCP Analytics/Shared filters',
    component: McpSharedFilters,
    args: {
        pageKey: 'mcp-shared-filters-story',
        dataAttrPrefix: 'mcp-shared-filters-story',
        refreshing: false,
        onRefresh: () => {},
        children: <McpDateFilter dateFrom="-7d" dateTo={null} onChange={() => {}} dataAttr="mcp-story-date-filter" />,
    },
    parameters: {
        pageUrl: urls.mcpAnalyticsDashboard(),
        mockDate: '2026-09-15T12:00:00Z',
    },
}
export default meta

type Story = StoryObj<typeof McpSharedFilters>

export const Empty: Story = {}

const applyActiveFilters: NonNullable<Story['play']> = async ({ canvas }) => {
    await canvas.findByRole('button', { name: 'Refresh' })
    if (!mcpAnalyticsFiltersLogic.isMounted()) {
        throw new Error('Shared filter logic is not mounted')
    }
    const team = teamLogic.values.currentTeam
    if (team) {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...team,
            test_account_filters: [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.IContains,
                    value: '@example.com',
                },
            ],
        })
    }
    mcpAnalyticsFiltersLogic.actions.setPropertyFilters(FILTERS)
    mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true)
}

export const Active: Story = {
    play: applyActiveFilters,
}

export const Narrow: Story = {
    play: applyActiveFilters,
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
