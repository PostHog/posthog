import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { IconBlank } from 'lib/lemon-ui/icons'

import { MCP_DASHBOARD_CARDS, McpDashboardCardId } from './dashboardCards'
import { mcpDashboardCardsLogic } from './mcpDashboardCardsLogic'

export function DashboardCardsMenu({ cardsWithoutData }: { cardsWithoutData: McpDashboardCardId[] }): JSX.Element {
    const { hiddenCount, isCardVisible } = useValues(mcpDashboardCardsLogic)
    const { toggleCard, showAllCards } = useActions(mcpDashboardCardsLogic)

    return (
        <LemonMenu
            closeOnClickInside={false}
            items={[
                {
                    items: MCP_DASHBOARD_CARDS.map(({ id, label }) => ({
                        label,
                        onClick: () => toggleCard(id),
                        icon: isCardVisible(id) ? <IconCheck /> : <IconBlank />,
                        tooltip: cardsWithoutData.includes(id) ? 'No data in this date range' : undefined,
                        'data-attr': `mcp-dashboard-card-${id}`,
                    })),
                },
                hiddenCount > 0 && {
                    items: [
                        { label: 'Show all cards', onClick: showAllCards, 'data-attr': 'mcp-dashboard-show-all-cards' },
                    ],
                },
            ]}
        >
            <LemonButton
                type="secondary"
                size="small"
                className="whitespace-nowrap"
                data-attr="mcp-dashboard-customize"
            >
                {hiddenCount > 0 ? `${hiddenCount} hidden` : 'Customize'}
            </LemonButton>
        </LemonMenu>
    )
}
