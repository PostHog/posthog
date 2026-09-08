import { pluralize } from 'lib/utils/strings'

import type { RowShiftApi, ShiftBandApi } from '../generated/api.schemas'

/** How far the rows moved, the larger side when inserts and deletes cancel out. Zero when the pair aligned with no shift. */
export function shiftedRows(rowShift: RowShiftApi | null | undefined): number {
    return rowShift ? Math.max(rowShift.inserted_rows, rowShift.deleted_rows) : 0
}

/** Only name a position when there is one band, so it can't point at one of several. */
function shiftPosition(rowShift: RowShiftApi): string {
    return rowShift.bands.length === 1 ? ` at y=${rowShift.bands[0].y}` : ''
}

function formatResidual(value: number): string {
    if (value === 0) {
        return '0%'
    }
    return value < 0.01 ? `${value.toFixed(3)}%` : `${value.toFixed(2)}%`
}

/**
 * The movement in pixels, the same number the classifier judged. Signed when
 * the page only grew or only shrank; unsigned when rows moved both ways,
 * because the net height change would understate how far they moved.
 */
function signedShiftPx(rowShift: RowShiftApi): string {
    const px = `${shiftedRows(rowShift)}px`
    if (rowShift.deleted_rows === 0) {
        return `+${px}`
    }
    if (rowShift.inserted_rows === 0) {
        return `-${px}`
    }
    return px
}

function absorbedTooltip(rowShift: RowShiftApi): string {
    const where = shiftPosition(rowShift)
    let opening: string
    if (rowShift.deleted_rows === 0) {
        opening = `The page grew by ${pluralize(rowShift.inserted_rows, 'row')}${where}.`
    } else if (rowShift.inserted_rows === 0) {
        opening = `The page shrank by ${pluralize(rowShift.deleted_rows, 'row')}${where}.`
    } else {
        opening = `The page shifted by ${pluralize(shiftedRows(rowShift), 'row')}${where}.`
    }
    return (
        `${opening} Rows below it moved, and after aligning them only ${formatResidual(rowShift.residual_percentage)} ` +
        `of pixels differ, so this run was absorbed as noise. Without alignment it would have read as ` +
        `${rowShift.raw_diff_percentage.toFixed(2)}% pixel diff.`
    )
}

function layoutTooltip(rowShift: RowShiftApi): string {
    const parts: string[] = []
    if (rowShift.inserted_rows > 0) {
        parts.push(`${pluralize(rowShift.inserted_rows, 'row')} added`)
    }
    if (rowShift.deleted_rows > 0) {
        parts.push(`${pluralize(rowShift.deleted_rows, 'row')} removed`)
    }
    return (
        `${parts.join(' and ')}${shiftPosition(rowShift)}. Content in the matched rows changed by ` +
        `${formatResidual(rowShift.residual_percentage)} (residual).`
    )
}

export interface ShiftDescription {
    /** `neutral` for an absorbed shift, which needs no review; `warning` for a layout change. */
    tone: 'neutral' | 'warning'
    label: string
    compactLabel: string
    tooltip: string
}

/**
 * The one description both the badge and its predicate render from, so the
 * two cannot disagree about whether a snapshot has a shift worth showing.
 *
 * Chips speak pixels because that is the size of the move a person sees;
 * tooltips and the sidebar speak rows with positions, which is what somebody
 * chasing the cause needs. Returns null when nothing moved.
 */
export function describeShift(rowShift: RowShiftApi | null | undefined, absorbed: boolean): ShiftDescription | null {
    if (!rowShift || shiftedRows(rowShift) === 0) {
        return null
    }
    const px = signedShiftPx(rowShift)
    if (absorbed) {
        const magnitude = `${shiftedRows(rowShift)}px shift`
        return {
            tone: 'neutral',
            label: `Absorbed ${magnitude}`,
            compactLabel: magnitude,
            tooltip: absorbedTooltip(rowShift),
        }
    }
    return {
        tone: 'warning',
        label: `${px} Layout shift`,
        compactLabel: px,
        tooltip: layoutTooltip(rowShift),
    }
}

/** One band, as the sidebar names it. */
export function describeBand(band: ShiftBandApi): string {
    const verb = band.kind === 'deleted' ? 'deleted' : 'inserted'
    return `${pluralize(band.rows, 'row')} ${verb} at y=${band.y}`
}
