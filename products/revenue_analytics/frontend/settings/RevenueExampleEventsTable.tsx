import { useValues } from 'kea'
import { DEFAULT_CURRENCY } from 'lib/utils/geography/currency'

import { Query } from '~/queries/Query/Query'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'
import { Currency, Revenue } from './RevenueExampleTableColumns'

const queryContext: QueryContext = {
    showOpenEditorButton: true,
    columns: {
        original_amount: {
            title: 'Ingested amount',
        },
        currency_aware_amount: {
            title: 'Parsed amount',
            render: ({ value, record }) => {
                const adjustedCurrency = (record as any[])[4]
                return <Revenue value={value as number} currency={adjustedCurrency ?? DEFAULT_CURRENCY} />
            },
        },
        original_currency: {
            title: 'Ingested currency',
            render: ({ value }) => {
                return <Currency currency={value as CurrencyCode} />
            },
        },
        currency: {
            render: ({ value }) => {
                return <Currency currency={value as CurrencyCode} />
            },
        },
        amount: {
            render: ({ value, record }) => {
                const convertedCurrency = (record as any[])[6]
                return <Revenue value={value as number} currency={convertedCurrency ?? DEFAULT_CURRENCY} />
            },
        },
    },
}

export function RevenueExampleEventsTable(): JSX.Element | null {
    const { exampleEventsQuery } = useValues(revenueAnalyticsSettingsLogic)

    if (!exampleEventsQuery) {
        return null
    }

    return (
        <div>
            <h3>Revenue events</h3>
            <p>
                The following revenue events are available in your data. This is helpful when you're trying to debug
                what your revenue events look like.
            </p>

            <Query query={exampleEventsQuery} context={queryContext} />
        </div>
    )
}
