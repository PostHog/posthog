import type { ScannerStatus } from '../scannerStatus'

export type StatusTone = 'success' | 'warning' | 'danger' | 'muted'

// Green and yellow mean the scanner is still sweeping, so their dot pulses. Tailwind's own pulse runs at 2s,
// which reads as urgent, so this slows it to 3s; reduced-motion users get a still dot.
const ACTIVE_PULSE = 'animate-[pulse_3s_cubic-bezier(0.4,0,0.6,1)_infinite] motion-reduce:animate-none'

const TONE_DOT: Record<StatusTone, string> = {
    success: 'bg-success',
    warning: 'bg-warning',
    danger: 'bg-danger',
    muted: 'bg-muted',
}

const STATUS_LABEL: Record<ScannerStatus['kind'], { label: string; tone: StatusTone }> = {
    off: { label: 'Off', tone: 'muted' },
    limit_reached: { label: 'Stopped', tone: 'danger' },
    quota_exhausted: { label: 'Stopped', tone: 'danger' },
    filter_error: { label: 'Filter error', tone: 'danger' },
    starting: { label: 'Starting', tone: 'warning' },
    delayed: { label: 'Delayed', tone: 'warning' },
    no_matches: { label: 'No matches', tone: 'warning' },
    throttled: { label: 'Throttled', tone: 'warning' },
    running: { label: 'Running', tone: 'success' },
}

export function scannerStatusTone(status: ScannerStatus): StatusTone {
    return STATUS_LABEL[status.kind].tone
}

/** The status dot and label, shared by the scanner list and the scanner page so the two always agree. */
export function ScannerStatusLabel({ status, className }: { status: ScannerStatus; className?: string }): JSX.Element {
    const { label, tone } = STATUS_LABEL[status.kind]
    return (
        <span className={`inline-flex items-center gap-2 ${className ?? ''}`}>
            <span
                className={`size-2 rounded-full shrink-0 ${TONE_DOT[tone]} ${
                    tone === 'success' || tone === 'warning' ? ACTIVE_PULSE : ''
                }`}
                aria-hidden
            />
            <span>{label}</span>
        </span>
    )
}
