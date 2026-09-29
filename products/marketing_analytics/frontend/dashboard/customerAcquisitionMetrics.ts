import { WebOverviewItem } from '~/queries/schema/schema-general'

export function customerAcquisitionMetrics(
    customerResults: WebOverviewItem[] | undefined,
    trafficResults: WebOverviewItem[] | undefined
): WebOverviewItem[] {
    const customers = customerResults?.find((item) => item.key === 'unique conversions')
    if (!customers) {
        return []
    }
    const visitors = trafficResults?.find((item) => item.key === 'visitors')
    const ratio = (numerator: number | undefined, denominator: number | undefined): number | undefined =>
        numerator != null && denominator != null && denominator > 0 ? (100 * numerator) / denominator : undefined
    const value = ratio(customers.value, visitors?.value)
    const previous = ratio(customers.previous, visitors?.previous)
    return [
        customers,
        {
            ...customerResults?.find((item) => item.key === 'conversion rate'),
            key: 'conversion rate',
            kind: 'percentage',
            value,
            previous,
            changeFromPreviousPct:
                value != null && previous != null && previous > 0
                    ? Math.round((100 * (value - previous)) / previous)
                    : undefined,
        },
    ]
}
