import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'
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
                return <Revenue value={value as number} currency={originalCurrency ?? CurrencyCode.USD} />
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
                return <Revenue value={value as number} currency={convertedCurrency ?? CurrencyCode.USD} />
            },
        },
    },
}

export function RevenueExampleDataWarehouseTablesData(): JSX.Element | null {
    const { exampleDataWarehouseTablesQuery } = useValues(revenueEventsSettingsLogic)

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
