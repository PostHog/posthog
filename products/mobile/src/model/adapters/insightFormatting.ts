import { asRecord } from '@/lib/records'
import type { InsightValueFormat } from '@/model/views'

import { asTrendsInsight, chartFormat, formatMetricValue } from './metric'
import { sqlValuePresentation } from './sqlVisualization'

function precision(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100 ? value : undefined
}

function text(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

/** `columns` and `types` are a SQL response's own; a SQL format depends on which result column is the first y. */
export function insightValueFormat(query: unknown, columns?: unknown, types?: unknown): InsightValueFormat {
    const node = asRecord(query)
    const source = asRecord(node?.source) ?? node
    const format = chartFormat(asTrendsInsight(query))
    if (source?.kind === 'HogQLQuery') {
        const presentation = sqlValuePresentation(query, columns, types)
        return {
            ...format,
            ...(presentation.style === 'percent' ? { valueFormat: 'percentage' as const } : {}),
            presentation,
        }
    }
    if (source?.kind !== 'TrendsQuery') {
        return format
    }
    const filter = asRecord(source.trendsFilter)
    const style = typeof filter?.aggregationAxisFormat === 'string' ? filter.aggregationAxisFormat : null
    return {
        ...format,
        ...(style === 'currency' ? { valueFormat: 'currency' as const, unit: 'USD' } : {}),
        ...(style === 'duration_ns' ? { valueFormat: 'duration' as const, unit: 'ns' } : {}),
        presentation: {
            kind: 'trends',
            style,
            prefix: text(filter?.aggregationAxisPrefix),
            suffix: text(filter?.aggregationAxisPostfix),
            decimalPlaces: precision(filter?.decimalPlaces),
            minDecimalPlaces: precision(filter?.minDecimalPlaces),
        },
    }
}

function number(value: number, maximumFractionDigits: number, minimumFractionDigits = 0): string {
    return value.toLocaleString('en-US', {
        maximumFractionDigits: Math.max(maximumFractionDigits, minimumFractionDigits),
        minimumFractionDigits,
    })
}

function significantDecimals(value: number, minimum = 2): number {
    return !Number.isFinite(value) || value === 0
        ? minimum
        : Math.min(Math.max(minimum, 1 - Math.floor(Math.log10(Math.abs(value)))), 10)
}

function shortNumber(value: number): string {
    const magnitudes = ['', 'K', 'M', 'B', 'T', 'P', 'E', 'Z', 'Y']
    let rounded = Number(value.toPrecision(3))
    let magnitude = 0
    while (Math.abs(rounded) >= 1000 && magnitude < magnitudes.length - 1) {
        magnitude++
        rounded /= 1000
    }
    return magnitude ? `${rounded}\u00a0${magnitudes[magnitude]}` : String(rounded)
}

function duration(milliseconds: number): string {
    const absolute = Math.abs(milliseconds)
    if (absolute === 0) {
        return '0s'
    }
    if (absolute < 60_000) {
        const value = absolute < 1000 ? milliseconds : milliseconds / 1000
        const decimals = Math.min(Math.max(0, 2 - Math.floor(Math.log10(Math.abs(value)))), 4)
        return `${number(value, decimals)}${absolute < 1000 ? 'ms' : 's'}`
    }
    const seconds = Math.floor(absolute / 1000)
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const parts = days
        ? [
              [days, 'd'],
              [hours, 'h'],
          ]
        : [
              [hours, 'h'],
              [minutes, 'm'],
              [seconds % 60, 's'],
          ]
    return `${milliseconds < 0 ? '-' : ''}${parts
        .filter(([amount]) => amount)
        .map(([amount, unit]) => `${amount}${unit}`)
        .join('\u00a0')}`
}

// Mirrors formatDataWithSettings and formatAggregationAxisValue without importing the web app into the native bundle.
export function formatInsightValue(value: number, format: InsightValueFormat): string {
    const presentation = format.presentation
    if (!presentation) {
        return formatMetricValue(value, format.valueFormat, format.unit)
    }
    const { kind, style, prefix, suffix, decimalPlaces, minDecimalPlaces } = presentation
    let formatted: string
    if (kind === 'sql') {
        const scaled = value * (presentation.scale ?? 1)
        switch (style) {
            case 'number':
            case 'percent':
                formatted = number(scaled, decimalPlaces ?? 3, decimalPlaces ?? 0)
                if (style === 'percent') {
                    formatted += '%'
                }
                break
            case 'short':
                formatted = shortNumber(scaled)
                break
            default:
                formatted = decimalPlaces === undefined ? String(scaled) : scaled.toFixed(decimalPlaces)
        }
    } else {
        const scaled = style === 'percentage_scaled' ? value * 100 : value
        formatted = number(scaled, decimalPlaces ?? significantDecimals(scaled, minDecimalPlaces), minDecimalPlaces)
        switch (style) {
            case 'percentage':
            case 'percentage_scaled':
                formatted = `${number(scaled, decimalPlaces ?? significantDecimals(scaled, minDecimalPlaces))}%`
                break
            case 'currency':
                formatted = `$${number(value, 2, 2)}`
                break
            case 'short':
                formatted = shortNumber(value)
                break
            case 'duration':
                formatted = duration(value * 1000)
                break
            case 'duration_ms':
                formatted = duration(value)
                break
            case 'duration_ns':
                formatted =
                    Math.abs(value) < 1000
                        ? `${number(value, 2)}ns`
                        : Math.abs(value) < 1_000_000
                          ? `${number(value / 1000, 2)}µs`
                          : duration(value / 1_000_000)
                break
        }
    }
    const effectivePrefix = style === 'currency' && prefix && formatted.startsWith(prefix) ? '' : prefix
    return `${effectivePrefix}${formatted}${suffix}`
}
