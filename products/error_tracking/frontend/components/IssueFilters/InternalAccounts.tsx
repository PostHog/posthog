import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, Label, Switch, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { issueFiltersLogic } from './issueFiltersLogic'

export const InternalAccountsFilter = (): JSX.Element => {
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const disabledReason = hasFilters ? undefined : "You haven't set any internal and test filters"

    return (
        <div className="flex h-7 shrink-0 items-center gap-1" title={disabledReason}>
            <Label htmlFor="error-tracking-test-account-filter" className="whitespace-nowrap">
                Exclude internal users
            </Label>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="default"
                            size="icon-sm"
                            render={
                                <LinkPrimitive
                                    to={urls.settings('environment-customization', 'internal-user-filtering')}
                                />
                            }
                            aria-label="Configure internal user filters"
                        />
                    }
                >
                    <IconGear />
                </TooltipTrigger>
                <TooltipContent>Configure internal user filters</TooltipContent>
            </Tooltip>
            <Switch
                id="error-tracking-test-account-filter"
                size="default"
                checked={hasFilters && filterTestAccounts}
                disabled={!hasFilters}
                onCheckedChange={(checked) => {
                    setFilterTestAccounts(checked)
                    setLocalDefault(checked)
                }}
                aria-label="Exclude internal users"
            />
        </div>
    )
}
