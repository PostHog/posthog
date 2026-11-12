import { useActions, useValues } from 'kea'

import { IconChevronDown, IconGear } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'

type InternalUsersMode = 'include' | 'exclude'

export function McpInternalUsersFilter({ dataAttr }: { dataAttr: string }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { filterTestAccounts } = useValues(mcpAnalyticsFiltersLogic)
    const { setFilterTestAccounts } = useActions(mcpAnalyticsFiltersLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const excluded = hasFilters && filterTestAccounts

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" data-attr={dataAttr} />}>
                <span>{excluded ? 'Internal users excluded' : 'Internal users included'}</span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-64">
                <DropdownMenuRadioGroup
                    value={excluded ? 'exclude' : 'include'}
                    onValueChange={(value: InternalUsersMode) => setFilterTestAccounts(value === 'exclude')}
                >
                    <DropdownMenuRadioItem value="include" closeOnClick>
                        Include internal and test users
                    </DropdownMenuRadioItem>
                    <DropdownMenuRadioItem
                        value="exclude"
                        closeOnClick
                        disabledReason={hasFilters ? undefined : 'Configure internal and test users first.'}
                    >
                        Exclude internal and test users
                    </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={
                        <Button
                            className="w-full font-normal"
                            left
                            render={
                                <LinkPrimitive
                                    to={urls.settings('environment-customization', 'internal-user-filtering')}
                                    target="_blank"
                                />
                            }
                        />
                    }
                >
                    <IconGear />
                    Configure internal and test users
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
