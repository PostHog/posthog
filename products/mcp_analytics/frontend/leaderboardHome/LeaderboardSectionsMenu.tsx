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

import { leaderboardSectionTitle } from './leaderboardSections'
import { mcpLeaderboardSectionsLogic } from './mcpLeaderboardSectionsLogic'

export function LeaderboardSectionsMenu(): JSX.Element {
    const { availableSectionIds, hiddenSections, isSectionVisible } = useValues(mcpLeaderboardSectionsLogic)
    const { toggleSection, showAllSections } = useActions(mcpLeaderboardSectionsLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={<Button variant="outline" className="whitespace-nowrap" data-attr="mcp-dashboard-customize" />}
            >
                <span>{hiddenSections.length > 0 ? `${hiddenSections.length} hidden` : 'Customize'}</span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                {availableSectionIds.map((id) => (
                    <DropdownMenuCheckboxItem
                        key={id}
                        checked={isSectionVisible(id)}
                        onCheckedChange={() => toggleSection(id)}
                        closeOnClick={false}
                        data-attr={`mcp-dashboard-section-${id}`}
                    >
                        {leaderboardSectionTitle(id)}
                    </DropdownMenuCheckboxItem>
                ))}
                {hiddenSections.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            onClick={showAllSections}
                            closeOnClick={false}
                            data-attr="mcp-dashboard-show-all-sections"
                        >
                            Show all sections
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
