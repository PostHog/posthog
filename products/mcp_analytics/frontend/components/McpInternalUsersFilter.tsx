import { useActions, useValues } from 'kea'

import { IconBuilding, IconExternal } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'

export function McpInternalUsersFilter({ dataAttr }: { dataAttr: string }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { filterTestAccounts } = useValues(mcpAnalyticsFiltersLogic)
    const { setFilterTestAccounts } = useActions(mcpAnalyticsFiltersLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const excluded = hasFilters && filterTestAccounts
    const label = excluded ? 'Internal users excluded' : 'Internal users included'

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label={label}
                        aria-pressed={excluded}
                        title={label}
                        data-attr={dataAttr}
                    />
                }
            >
                <span className="relative flex size-4 items-center justify-center">
                    <IconBuilding className={excluded ? 'size-4 text-[var(--primary)]' : 'size-4'} />
                    {excluded ? (
                        <span className="absolute h-px w-5 -rotate-45 rounded-full bg-[var(--primary)]" aria-hidden />
                    ) : null}
                </span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
                <DropdownMenuCheckboxItem
                    checked={excluded}
                    disabled={!hasFilters}
                    closeOnClick={false}
                    title={hasFilters ? undefined : 'Configure internal and test users first.'}
                    onCheckedChange={(checked: boolean) => setFilterTestAccounts(checked)}
                >
                    Exclude internal and test users
                </DropdownMenuCheckboxItem>
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
                    <IconExternal />
                    Configure internal and test users
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
