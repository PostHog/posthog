import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import type { RunVariant } from '../cards/runStatusVariant'
import type { QuillDetailLine } from './QuillDetailSection'

const RUN_VARIANT_PHRASES: Record<RunVariant, string> = {
    live: 'In progress',
    queued: 'Queued',
    failed: 'Failed',
    completed: 'Finished',
}

/** What the closed Runs line says. `variants` holds one entry per run, with the newest run first. */
export function reportRunsLine(variants: RunVariant[]): string {
    const count = `${variants.length} ${variants.length === 1 ? 'run' : 'runs'}`
    if (variants.length === 0) {
        return count
    }
    const latest = RUN_VARIANT_PHRASES[variants[0]]
    return variants.length === 1 ? `${count} · ${latest}` : `${count} · The last one: ${latest.toLowerCase()}`
}

/** What the closed Follow-up checks line says. A failed check shows here, so nobody has to open the line to find it. */
export function reportChecksLine(checks: SignalReportCheckApi[], meta: string): QuillDetailLine {
    const failed = checks.filter((check) => check.status === 'failed').length
    if (failed > 0) {
        return { text: `${failed} of ${checks.length} failed`, tone: 'risk' }
    }
    const [, state] = meta.split(' · ')
    const count = `${checks.length} ${checks.length === 1 ? 'check' : 'checks'}`
    return { text: state ? `${count} · ${state.charAt(0).toUpperCase()}${state.slice(1)}` : count }
}
