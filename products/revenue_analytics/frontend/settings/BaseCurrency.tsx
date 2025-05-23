import { useActions, useValues } from 'kea'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

export function BaseCurrency(): JSX.Element {
    const { baseCurrency } = useValues(revenueAnalyticsSettingsLogic)
    const { updateBaseCurrency, save } = useActions(revenueAnalyticsSettingsLogic)

    return (
        <div>
            <h3>Base currency</h3>
            <p>
                PostHog will convert all revenue values to this currency before displaying them to you. If we can't
                properly detect your revenue events' currency, we'll assume it's in this currency as well.
            </p>
            <CurrencyDropdown
                value={baseCurrency}
                onChange={(currency) => {
                    updateBaseCurrency(currency as CurrencyCode)
                    save()
                }}
            />
        </div>
    )
}
