import { PRIORITY_THRESHOLD_OPTIONS, SignalReportPriority } from '../types'

const LABELS: Record<SignalReportPriority, string> = { P0: 'P0', P1: 'P1+', P2: 'P2+', P3: 'P3+', P4: 'All' }

export const AUTONOMY_PRIORITY_OPTIONS = PRIORITY_THRESHOLD_OPTIONS.map(({ value }) => ({
    value,
    label: LABELS[value],
}))
