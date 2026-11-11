import { formatAggregationAxisValue } from 'lib/insights/aggregationAxisFormat'
import { getCurrencySymbol } from 'lib/utils/currency'
import { humanFriendlyNumber, significantDecimalPlaces } from 'lib/utils/numbers'

import { CurrencyCode, ExperimentMetricValueFormatType } from '~/queries/schema/schema-general'

function formatCurrencyAmount(value: number, currency: CurrencyCode): string {
    const { symbol, isPrefix } = getCurrencySymbol(currency)
    // The value of a mean metric is an average per user, which is often far below 1. Two decimals would show
    // 0.0342 and 0.0358 as 0.03 and 0.04, so an amount below 1 keeps three significant digits.
    const decimals = Math.abs(value) < 1 ? significantDecimalPlaces(value) + 1 : 2
    const amount = humanFriendlyNumber(Math.abs(value), decimals, 2)
    const sign = value < 0 ? '-' : ''
    return isPrefix ? `${sign}${symbol}${amount}` : `${sign}${amount} ${symbol}`
}

export function formatValueAs(
    value: number,
    type: ExperimentMetricValueFormatType,
    baseCurrency: CurrencyCode
): string {
    if (type === 'currency') {
        return formatCurrencyAmount(value, baseCurrency)
    }
    return formatAggregationAxisValue({ aggregationAxisFormat: type }, value)
}
