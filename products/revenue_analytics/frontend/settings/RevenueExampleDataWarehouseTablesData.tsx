import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { Query } from '~/queries/Query/Query'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { Currency, Revenue } from './RevenueExampleTableColumns'
import { revenueAnalyticsSettingsLogic } from './revenueAnalyticsSettingsLogic'

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
    const { exampleDataWarehouseTablesQuery } = useValues(revenueAnalyticsSettingsLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    if (!exampleDataWarehouseTablesQuery) {
        return null
    }

    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            className={cn(!newSceneLayout && 'gap-y-0')}
            title="Data warehouse tables revenue data"
            description="The following rows of data were imported from your data warehouse tables. This is helpful when you're trying to debug what your revenue data looks like."
        >
            {!newSceneLayout && (
                <>
                    <h3>Data warehouse tables revenue data</h3>
                    <p>
                        The following rows of data were imported from your data warehouse tables. This is helpful when
                        you're trying to debug what your revenue data looks like.
                    </p>
                </>
            )}

            <Query query={exampleDataWarehouseTablesQuery} context={queryContext} />
        </SceneSection>
    )
}
