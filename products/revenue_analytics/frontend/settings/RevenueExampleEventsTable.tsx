import { useValues } from 'kea'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { Query } from '~/queries/Query/Query'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { Currency, Revenue } from './RevenueExampleTableColumns'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

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
                return <Revenue value={value as number} currency={adjustedCurrency ?? CurrencyCode.USD} />
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
                return <Revenue value={value as number} currency={convertedCurrency ?? CurrencyCode.USD} />
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
        <SceneSection
            title="Revenue events"
            description="The following revenue events are available in your data. This is helpful when you're trying to debug what your revenue events look like."
        >
            <Query attachTo={revenueAnalyticsSettingsLogic} query={exampleEventsQuery} context={queryContext} />
        </SceneSection>
    )
}
