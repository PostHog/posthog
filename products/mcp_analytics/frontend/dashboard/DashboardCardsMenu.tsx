import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import { MCP_DASHBOARD_CARDS, McpDashboardCardId } from './dashboardCards'
import { mcpDashboardCardsLogic } from './mcpDashboardCardsLogic'

export function DashboardCardsMenu({ cardsWithoutData }: { cardsWithoutData: McpDashboardCardId[] }): JSX.Element {
    const { hiddenCards, isCardVisible } = useValues(mcpDashboardCardsLogic)
    const { toggleCard, showAllCards } = useActions(mcpDashboardCardsLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" className="whitespace-nowrap" data-attr="mcp-dashboard-customize" />}
            >
                <span>{hiddenCards.length > 0 ? `${hiddenCards.length} hidden` : 'Customize'}</span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                {MCP_DASHBOARD_CARDS.map(({ id, label }) => (
                    <DropdownMenuCheckboxItem
                        key={id}
                        checked={isCardVisible(id)}
                        onCheckedChange={() => toggleCard(id)}
                        closeOnClick={false}
                        tooltip={cardsWithoutData.includes(id) ? 'No data in this date range' : undefined}
                        data-attr={`mcp-dashboard-card-${id}`}
                    >
                        {label}
                    </DropdownMenuCheckboxItem>
                ))}
                {hiddenCards.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            onClick={showAllCards}
                            closeOnClick={false}
                            data-attr="mcp-dashboard-show-all-cards"
                        >
                            Show all cards
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
