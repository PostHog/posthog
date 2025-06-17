import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function FilterTestAccountsConfiguration(): JSX.Element {
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)

    return (
        <div>
            <h3 className="mb-2">Filter test accounts out of revenue analytics</h3>
            <p className="mb-4">
                When enabled, events from test accounts will be excluded from Revenue analytics. You can configure these
                tests account{' '}
                <Link to={urls.settings('project-product-analytics', 'internal-user-filtering')}>here</Link>.
            </p>

            <LemonSwitch
                onChange={updateFilterTestAccounts}
                checked={filterTestAccounts}
                label="Filter test accounts out of revenue analytics"
                bordered
            />
        </div>
    )
}
