import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown, IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'

export function McpInternalUsersFilter({ dataAttr }: { dataAttr: string }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { filterTestAccounts } = useValues(mcpAnalyticsFiltersLogic)
    const { setFilterTestAccounts } = useActions(mcpAnalyticsFiltersLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const excluded = hasFilters && filterTestAccounts

    return (
        <LemonMenu
            items={[
                {
                    items: [
                        {
                            label: 'Include internal and test users',
                            icon: !excluded ? <IconCheck /> : undefined,
                            onClick: () => setFilterTestAccounts(false),
                        },
                        {
                            label: 'Exclude internal and test users',
                            icon: excluded ? <IconCheck /> : undefined,
                            disabledReason: hasFilters ? undefined : 'Configure internal and test users first.',
                            onClick: () => setFilterTestAccounts(true),
                        },
                    ],
                },
                {
                    items: [
                        {
                            label: 'Configure internal and test users',
                            icon: <IconGear />,
                            to: urls.settings('environment-customization', 'internal-user-filtering'),
                            targetBlank: true,
                        },
                    ],
                },
            ]}
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />} data-attr={dataAttr}>
                {excluded ? 'Internal users excluded' : 'Internal users included'}
            </LemonButton>
        </LemonMenu>
    )
}
