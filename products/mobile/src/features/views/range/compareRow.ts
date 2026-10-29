import type { ViewRange } from '../rangeStore'
import type { RangeCompareRow } from './RangeSheet'

const NOTE_ON = 'Shows the previous period as a dashed line'
const NOTE_OFF = 'Off'
const NOTE_ALL_TIME = 'All time has no previous period to compare with.'
const NOTE_DASHBOARD = 'Compare works on single insights. Open a chart to compare.'

/** The compare row of an insight. With All time the server turns compare off, so the switch is off and disabled. */
export function insightCompareRow(range: ViewRange, available: boolean): RangeCompareRow {
    return {
        on: available && range.compare,
        enabled: available,
        note: available ? (range.compare ? NOTE_ON : NOTE_OFF) : NOTE_ALL_TIME,
        onChange: range.setCompare,
    }
}

/** The compare row of a dashboard: disabled with its note until the server accepts compare in a dashboard override. */
export function dashboardCompareRow(range: ViewRange, supported: boolean): RangeCompareRow {
    if (!supported) {
        return { on: false, enabled: false, note: NOTE_DASHBOARD, onChange: () => undefined }
    }
    return insightCompareRow(range, range.preset !== 'all')
}
