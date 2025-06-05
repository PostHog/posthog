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
        original_currency: {
            render: ({ value }) => {
                return <Currency currency={value as CurrencyCode} />
            },
        },
        original_revenue: {
            render: ({ value, record }) => {
                const originalCurrency = (record as any[])[3]
                return <Revenue value={value as number} currency={originalCurrency ?? DEFAULT_CURRENCY} />
            },
        },
        currency: {
            render: ({ value }) => {
                return <Currency currency={value as CurrencyCode} />
            },
        },
        revenue: {
            render: ({ value, record }) => {
                const convertedCurrency = (record as any[])[5]
                return <Revenue value={value as number} currency={convertedCurrency ?? DEFAULT_CURRENCY} />
            },
        },
    },
}

export function RevenueExampleDataWarehouseTablesData(): JSX.Element | null {
    const { exampleDataWarehouseTablesQuery } = useValues(revenueAnalyticsSettingsLogic)

    if (!exampleDataWarehouseTablesQuery) {
        return null
    }

    return (
        <div>
            <h3>Data warehouse tables revenue data</h3>
            <p>
                The following rows of data were imported from your data warehouse tables. This is helpful when you're
                trying to debug what your revenue data looks like.
            </p>

            <Query query={exampleDataWarehouseTablesQuery} context={queryContext} />
        </div>
    )
}
