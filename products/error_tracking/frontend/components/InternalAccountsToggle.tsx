import { useActions, useValues } from 'kea'

import { IconBuilding, IconExternal } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export interface InternalAccountsToggleProps {
    filterTestAccounts: boolean
    onChange: (filterTestAccounts: boolean) => void
}

/** Error tracking's internal-user exclusion toggle, with a shortcut to configure the filters. */
export const InternalAccountsToggle = ({ filterTestAccounts, onChange }: InternalAccountsToggleProps): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const disabledReason = hasFilters ? undefined : "You haven't set any internal and test filters"
    const isFiltering = hasFilters && filterTestAccounts

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon"
                        aria-label="Internal user filters"
                        aria-pressed={isFiltering}
                        title="Internal user filters"
                        data-attr="error-tracking-internal-user-filters"
                    />
                }
            >
                <span
                    className={
                        isFiltering
                            ? 'relative flex size-4 items-center justify-center text-[var(--primary)]'
                            : 'flex size-4 items-center justify-center'
                    }
                >
                    <IconBuilding className={isFiltering ? 'size-4 text-[var(--primary)]' : 'size-4'} />
                    {isFiltering ? (
                        <span className="absolute h-px w-5 -rotate-45 rounded-full bg-current" aria-hidden />
                    ) : null}
                </span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuCheckboxItem
                    checked={isFiltering}
                    disabled={!hasFilters}
                    closeOnClick={false}
                    title={disabledReason}
                    data-attr="error-tracking-exclude-internal-users"
                    onCheckedChange={(checked: boolean) => {
                        onChange(checked)
                        setLocalDefault(checked)
                    }}
                >
                    Exclude internal users
                </DropdownMenuCheckboxItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={
                        <Button
                            variant="default"
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
                    Configure internal user filters
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
