import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    ButtonGroup,
    ButtonGroupText,
    buttonVariants,
    cn,
    Label,
    Switch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export interface InternalAccountsToggleProps {
    filterTestAccounts: boolean
    onChange: (filterTestAccounts: boolean) => void
    /** Ties the label to the switch. Override when two instances can render on one page. */
    id?: string
}

/** Error tracking's internal-user exclusion toggle, with a shortcut to configure the filters. */
export const InternalAccountsToggle = ({
    filterTestAccounts,
    onChange,
    id = 'error-tracking-test-account-filter',
}: InternalAccountsToggleProps): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const disabledReason = hasFilters ? undefined : "You haven't set any internal and test filters"

    return (
        <ButtonGroup className="shrink-0" title={disabledReason}>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
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
            {/*
             * ButtonGroupText ships no frame, so this segment borrows the outline button's own
             * variant classes rather than re-deriving its border and fill, which is how the two
             * segments stay identical. It isn't a button, so the pointer cursor is dropped.
             */}
            <ButtonGroupText className={cn(buttonVariants({ variant: 'outline', size: 'default' }), 'cursor-default')}>
                <Label htmlFor={id} className="whitespace-nowrap">
                    Exclude internal users
                </Label>
                <Switch
                    id={id}
                    size="default"
                    checked={hasFilters && filterTestAccounts}
                    disabled={!hasFilters}
                    onCheckedChange={(checked) => {
                        onChange(checked)
                        setLocalDefault(checked)
                    }}
                    aria-label="Exclude internal users"
                />
            </ButtonGroupText>
        </ButtonGroup>
    )
}
