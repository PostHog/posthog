import { useActions, useValues } from 'kea'

import { IconBuilding, IconExternal } from '@posthog/icons'
import { LemonMenu, LemonSwitch } from '@posthog/lemon-ui'

import { Button } from 'lib/ui/quill'
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
    const isFiltering = hasFilters && filterTestAccounts

    return (
        <LemonMenu
            placement="bottom-end"
            closeOnClickInside={false}
            items={[
                {
                    custom: true,
                    label: () => (
                        <LemonSwitch
                            id={id}
                            className="min-h-8"
                            size="small"
                            fullWidth
                            checked={isFiltering}
                            disabledReason={disabledReason}
                            onChange={(checked) => {
                                onChange(checked)
                                setLocalDefault(checked)
                            }}
                            label="Exclude internal users"
                            labelClassName="text-sm"
                            data-attr="error-tracking-exclude-internal-users"
                        />
                    ),
                },
                {
                    label: 'Configure internal user filters',
                    to: urls.settings('environment-customization', 'internal-user-filtering'),
                    targetBlank: true,
                    sideIcon: <IconExternal />,
                },
            ]}
        >
            <Button
                variant="default"
                size="icon"
                aria-label="Internal user filters"
                aria-pressed={isFiltering}
                title="Internal user filters"
                data-attr="error-tracking-internal-user-filters"
            >
                <span
                    className={
                        isFiltering
                            ? 'relative flex size-4 items-center justify-center text-[var(--primary)]'
                            : 'flex size-4 items-center justify-center'
                    }
                >
                    <IconBuilding className={isFiltering ? 'size-4 text-[var(--primary)]' : 'size-4'} />
                    {isFiltering && (
                        <span className="absolute h-px w-5 -rotate-45 rounded-full bg-current" aria-hidden />
                    )}
                </span>
            </Button>
        </LemonMenu>
    )
}
