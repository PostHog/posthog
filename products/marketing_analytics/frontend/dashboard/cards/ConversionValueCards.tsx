import { useValues } from 'kea'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { CONVERSION_VALUE_LABELS, ConversionValueKey, ConversionValueLoaded } from './ConversionValueLoaded'
import { MetricNoticeCard } from './MetricNoticeCard'

const BOTH_KEYS: ConversionValueKey[] = ['conversion_value', 'avg_conversion_value']

export interface ConversionValueCardsProps {
    only?: ConversionValueKey
}

/** The value total and its average, or a pair of N/A notices when the goal totals no money
 * property. Both come from one query, so they cannot disagree with each other. */
export function ConversionValueCards({ only }: ConversionValueCardsProps = {}): JSX.Element {
    const { conversionValueQuery } = useValues(marketingDashboardLogic)
    const keys = only ? [only] : BOTH_KEYS

    if (!conversionValueQuery) {
        return (
            <>
                {keys.map((key) => (
                    <MetricNoticeCard
                        key={key}
                        title={CONVERSION_VALUE_LABELS[key]}
                        message="No value associated with this conversion."
                        value="N/A"
                    />
                ))}
            </>
        )
    }
    return <ConversionValueLoaded query={conversionValueQuery} keys={keys} />
}
