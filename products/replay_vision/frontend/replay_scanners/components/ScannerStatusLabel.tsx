import type { ScannerDisabledReasonEnumApi } from '../../generated/api.schemas'
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

type StatusLabel = { label: string; tone: StatusTone }

// A person's own turn-off stays a quiet "Off"; one PostHog made names its cause so it isn't mistaken for a choice.
const OFF_LABEL: Record<ScannerDisabledReasonEnumApi, StatusLabel> = {
    manual: { label: 'Off', tone: 'muted' },
    free_credits_used: { label: 'Stopped', tone: 'danger' },
    no_ai_consent: { label: 'Needs AI consent', tone: 'danger' },
    creator_lost_access: { label: 'Creator lost access', tone: 'danger' },
    experiment_deleted: { label: 'Experiment deleted', tone: 'muted' },
}

const STATUS_LABEL: Record<Exclude<ScannerStatus['kind'], 'off'>, StatusLabel> = {
    no_sampling: { label: 'Off', tone: 'muted' },
    replay_off: { label: 'Replay off', tone: 'danger' },
    no_recordings: { label: 'No recordings', tone: 'warning' },
    limit_reached: { label: 'Stopped', tone: 'danger' },
    quota_exhausted: { label: 'Stopped', tone: 'danger' },
    filter_error: { label: 'Filter error', tone: 'danger' },
    starting: { label: 'Starting', tone: 'warning' },
    delayed: { label: 'Delayed', tone: 'warning' },
    no_matches: { label: 'No matches', tone: 'warning' },
    throttled: { label: 'Throttled', tone: 'warning' },
    running: { label: 'Running', tone: 'success' },
}

function statusLabel(status: ScannerStatus): StatusLabel {
    if (status.kind === 'off') {
        return status.reason ? OFF_LABEL[status.reason] : OFF_LABEL.manual
    }
    return STATUS_LABEL[status.kind]
}

/** The status dot and label, shared by the scanner list and the scanner page so the two always agree. */
export function ScannerStatusLabel({ status, className }: { status: ScannerStatus; className?: string }): JSX.Element {
    const { label, tone } = statusLabel(status)
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
