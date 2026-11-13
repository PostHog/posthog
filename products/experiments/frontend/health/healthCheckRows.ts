import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { ExperimentHealthCheckResultApiRowsItem } from '../generated/api.schemas'
import { formatHealthPercentage, formatHours } from './healthCheckValues'
import type { HealthPanelCheck } from './healthPanelChecks'

type HealthRow = ExperimentHealthCheckResultApiRowsItem

/** One cell of a check's table: text, a variant shown with its color, or a time in the reader's zone. */
export type HealthRowCell = { text: string } | { variant: string } | { time: string }

export interface HealthRowsColumn {
    key: string
    title: string
    align?: 'right'
}

export interface HealthRowsTable {
    columns: HealthRowsColumn[]
    rows: Record<string, HealthRowCell>[]
}

/** A significant variant's difference against the smallest difference its sample can reliably detect. */
export interface HealthDetectableEffect {
    variant: string
    difference: number
    detectable: number
    /** The end of the shared scale, in percent, so every variant's line reads on the same axis. */
    scaleMax: number
}

function text(value: string): HealthRowCell {
    return { text: value }
}

function numberOf(row: HealthRow, key: string): number | null {
    const value = row[key]
    return typeof value === 'number' ? value : null
}

function stringOf(row: HealthRow, key: string): string | null {
    const value = row[key]
    return typeof value === 'string' ? value : null
}

function count(row: HealthRow, key: string): HealthRowCell {
    const value = numberOf(row, key)
    return text(value === null ? '' : humanFriendlyNumber(value, 0))
}

function percentage(value: number | null, signed = false): string {
    if (value === null) {
        return ''
    }
    const sign = signed && value > 0 ? '+' : ''
    return `${sign}${formatHealthPercentage(value)}`
}

function rowsOf(check: HealthPanelCheck): HealthRow[] {
    // An exposure check carries no rows.
    return 'rows' in check ? (check.rows ?? []) : []
}

function significanceTable(rows: HealthRow[]): HealthRowsTable {
    return {
        columns: [
            { key: 'variant', title: 'Variant' },
            { key: 'difference', title: 'Difference', align: 'right' },
            { key: 'detectable', title: 'Smallest reliable difference', align: 'right' },
            { key: 'significant', title: 'Significant', align: 'right' },
        ],
        rows: rows.map((row) => ({
            variant: { variant: stringOf(row, 'variant') ?? '' },
            difference: text(percentage(numberOf(row, 'difference_percentage'), true)),
            detectable: text(percentage(numberOf(row, 'detectable_difference_percentage'))),
            significant: text(row.significant === true ? 'Yes' : 'No'),
        })),
    }
}

function forcedTable(rows: HealthRow[], units: string): HealthRowsTable {
    return {
        columns: [
            { key: 'variant', title: 'Variant' },
            { key: 'matched', title: capitalizeFirstLetter(units), align: 'right' },
            { key: 'forced', title: 'Forced by a release condition', align: 'right' },
            { key: 'share', title: 'Share forced', align: 'right' },
        ],
        rows: rows.map((row) => ({
            variant: { variant: stringOf(row, 'variant') ?? '' },
            matched: count(row, 'variant_matched_count'),
            forced: count(row, 'forced_count'),
            share: text(percentage(numberOf(row, 'forced_percentage'))),
        })),
    }
}

function metricLabel(row: HealthRow): string {
    const name = stringOf(row, 'metric_name') ?? ''
    const side = stringOf(row, 'ratio_side')
    const role = stringOf(row, 'metric_role')
    const metric = side ? `${capitalizeFirstLetter(side)} of ${name}` : name
    return role ? `${metric} (${role})` : metric
}

function zeroMetricsTable(rows: HealthRow[], units: string): HealthRowsTable {
    return {
        columns: [
            { key: 'metric', title: 'Metric at 0 in every variant' },
            { key: 'samples', title: capitalizeFirstLetter(units), align: 'right' },
            { key: 'data', title: 'Data', align: 'right' },
        ],
        rows: rows.map((row) => {
            const hours = numberOf(row, 'data_hours')
            return {
                metric: text(metricLabel(row)),
                samples: count(row, 'sample_count'),
                data: text(hours === null ? '' : formatHours(hours)),
            }
        }),
    }
}

function changeEffect(row: HealthRow, units: string): string {
    if (row.before_exposure === true) {
        return 'Saved before anyone was exposed, so it moved nobody'
    }
    if (row.before_exposure === null) {
        return "Couldn't tell whether anyone was exposed before it"
    }
    return `Saved after ${units} were exposed`
}

function flagChangesTable(rows: HealthRow[], units: string): HealthRowsTable {
    return {
        columns: [
            { key: 'saved', title: 'Saved' },
            { key: 'effect', title: 'Effect' },
        ],
        rows: rows.map((row) => ({
            saved: { time: stringOf(row, 'changed_at') ?? '' },
            effect: text(changeEffect(row, units)),
        })),
    }
}

/** What a check read per variant, metric or flag change, as a table. Null for a check that read no rows. */
export function healthCheckRowsTable(check: HealthPanelCheck, units: string): HealthRowsTable | null {
    const rows = rowsOf(check)
    if (rows.length === 0) {
        return null
    }
    switch (check.key) {
        case 'early_significance':
            return significanceTable(rows)
        case 'forced_variant_release_condition':
            return forcedTable(rows, units)
        case 'metric_all_zero':
            return zeroMetricsTable(rows, units)
        case 'split_changed_mid_run':
        case 'bucketing_changed_mid_run':
        case 'release_conditions_changed_mid_run':
            return flagChangesTable(rows, units)
        default:
            return null
    }
}

function scaleMax(largest: number): number {
    // A quarter of headroom keeps the marker off the end of the line, and a multiple of 5 gives a readable axis.
    return Math.max(5, Math.ceil((largest * 1.25) / 5) * 5)
}

/** The significant variants of the significance check, each against the difference its sample can detect. */
export function healthDetectableEffects(check: HealthPanelCheck): HealthDetectableEffect[] {
    if (check.key !== 'early_significance') {
        return []
    }
    const effects = rowsOf(check)
        .filter((row) => row.significant === true)
        .flatMap((row) => {
            const variant = stringOf(row, 'variant')
            const difference = numberOf(row, 'difference_percentage')
            const detectable = numberOf(row, 'detectable_difference_percentage')
            return variant === null || difference === null || detectable === null
                ? []
                : [{ variant, difference, detectable }]
        })
    const max = scaleMax(Math.max(0, ...effects.flatMap((effect) => [Math.abs(effect.difference), effect.detectable])))
    return effects.map((effect) => ({ ...effect, scaleMax: max }))
}
