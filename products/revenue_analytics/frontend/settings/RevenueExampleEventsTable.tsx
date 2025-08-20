import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { SceneSection } from '~/layout/scenes/SceneContent'
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
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    if (!exampleEventsQuery) {
        return null
    }

    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            className={cn(!newSceneLayout && 'gap-y-0')}
            title="Revenue events"
            description="The following revenue events are available in your data. This is helpful when you're trying to debug what your revenue events look like."
        >
            {!newSceneLayout && (
                <>
                    <h3>Revenue events</h3>
                    <p>
                        The following revenue events are available in your data. This is helpful when you're trying to
                        debug what your revenue events look like.
                    </p>
                </>
            )}

            <Query query={exampleEventsQuery} context={queryContext} />
        </SceneSection>
    )
}
