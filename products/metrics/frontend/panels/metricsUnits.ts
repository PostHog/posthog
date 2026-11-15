/** UCUM unit formatting for metric values, as OTel writes the `unit` field.
 *
 * The mapping covers the units the OTel semantic conventions emit. An unknown
 * unit falls back to a compact number with the unit string appended, so a new
 * unit never breaks rendering — it just reads less cleanly until it is added here. */

import { significantDecimalPlaces } from 'lib/utils/numbers'

// A fixed two decimals renders every value below 0.005 as "0", so a small-valued axis repeats one label.
const compact = (value: number): string =>
    new Intl.NumberFormat('en-US', {
        notation: 'compact',
        maximumFractionDigits: significantDecimalPlaces(value),
    }).format(value)

const bytes = (value: number, base: 1000 | 1024): string => {
    const units = base === 1024 ? ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'] : ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    if (value === 0) {
        return '0 ' + units[0]
    }
    const magnitude = Math.min(Math.floor(Math.log(Math.abs(value)) / Math.log(base)), units.length - 1)
    const scaled = value / Math.pow(base, Math.max(magnitude, 0))
    return `${compact(scaled)} ${units[Math.max(magnitude, 0)]}`
}

const seconds = (value: number): string => {
    const abs = Math.abs(value)
    // Zero has no magnitude to scale, so it would otherwise fall through to the ns branch.
    if (abs >= 1 || abs === 0) {
        return `${compact(value)} s`
    }
    if (abs >= 1e-3) {
        return `${compact(value * 1e3)} ms`
    }
    if (abs >= 1e-6) {
        return `${compact(value * 1e6)} µs`
    }
    return `${compact(value * 1e9)} ns`
}

/** Whether a bare `1` (ratio) value reads as a percent. A ratio in 0..1 becomes a percent;
 * a count that happens to be in 0..1 is left alone by the caller passing a more specific unit. */
const RATIO_AS_PERCENT_MAX = 1

const fitsPercent = (value: number): boolean => Math.abs(value) <= RATIO_AS_PERCENT_MAX

const ratio = (value: number, asPercent: boolean): string => (asPercent ? `${compact(value * 100)}%` : compact(value))

/** Format one metric value with a UCUM unit. `unit` is the raw OTel string; `undefined`
 * or an unknown unit falls back to a compact number. */
export function formatMetricValue(value: number, unit: string | undefined): string {
    if (!unit) {
        return compact(value)
    }
    if (unit === 'By') {
        return bytes(value, 1024)
    }
    if (unit === 'KiBy' || unit === 'MiBy' || unit === 'GiBy') {
        // OTel sometimes prefixes a binary unit directly; normalise through bytes.
        const factor = unit === 'KiBy' ? 1024 : unit === 'MiBy' ? 1024 ** 2 : 1024 ** 3
        return bytes(value * factor, 1024)
    }
    if (unit === 's') {
        return seconds(value)
    }
    if (unit === 'ms') {
        return seconds(value / 1e3)
    }
    if (unit === 'us') {
        return seconds(value / 1e6)
    }
    if (unit === 'ns') {
        return seconds(value / 1e9)
    }
    if (unit === '%') {
        return `${compact(value)}%`
    }
    if (unit === '1') {
        // UCUM "one": a dimensionless ratio. Render small ratios as a percent.
        return ratio(value, fitsPercent(value))
    }
    if (unit === '1/s') {
        return `${compact(value)}/s`
    }
    if (unit === 'By/s') {
        // A rate over a byte counter: scale through bytes so it reads as throughput.
        return `${bytes(value, 1024)}/s`
    }
    if (unit.endsWith('/s')) {
        // "{request}/s", "{message}/s", etc. Show the count rate with the noun.
        const noun = unit.slice(0, -2).replace(/[{}]/g, '')
        return noun ? `${compact(value)} ${noun}/s` : `${compact(value)}/s`
    }
    return `${compact(value)} ${unit}`
}

/** A formatter for values one visual shows together: a chart's ticks and tooltips, a table, a bucket list.
 * A ratio picks percent or bare numbers once from all `values`, so one visual never shows `100%` next
 * to `1.5`. Every other unit formats each value on its own. */
export function metricValuesFormatter(unit: string | undefined, values: readonly number[]): (value: number) => string {
    if (unit === '1') {
        const asPercent = values.every(fitsPercent)
        return (value: number) => ratio(value, asPercent)
    }
    return (value: number) => formatMetricValue(value, unit)
}
