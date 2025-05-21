import { useActions, useValues } from 'kea'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'
import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function BaseCurrency(): JSX.Element {
    const { baseCurrency } = useValues(revenueEventsSettingsLogic)
    const { updateBaseCurrency, save } = useActions(revenueEventsSettingsLogic)

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
