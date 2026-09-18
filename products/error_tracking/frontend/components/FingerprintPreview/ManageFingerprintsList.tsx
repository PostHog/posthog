import { useValues } from 'kea'

import { LemonButton, LemonCheckbox, Spinner } from '@posthog/lemon-ui'

import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { FingerprintLabel } from './FingerprintLabel'
import { FingerprintSampleMap } from './fingerprintSamplesLogic'

interface ManageFingerprintsListProps {
    loading: boolean
    fingerprints: ErrorTrackingFingerprint[]
    samples: FingerprintSampleMap
    selected: string[]
    activeFingerprint: string | null
    onToggle: (fingerprint: string) => void
    onActivate: (fingerprint: string) => void
}

export function ManageFingerprintsList({
    loading,
    fingerprints,
    samples,
    selected,
    activeFingerprint,
    onToggle,
    onActivate,
}: ManageFingerprintsListProps): JSX.Element {
    const { timezone } = useValues(teamLogic)

    if (loading) {
        return (
            <div className="flex items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (fingerprints.length === 0) {
        return (
            <div className="flex items-center justify-center text-center text-muted">
                No fingerprints found for this issue.
            </div>
        )
    }

    return (
        <div className="flex min-h-0 flex-col overflow-y-auto">
            {fingerprints.map(({ fingerprint, created_at }) => {
                const sample = samples[fingerprint]
                const isActive = fingerprint === activeFingerprint
                const accessibleLabel = sample ? `${sample.type} ${sample.value}` : fingerprint

                return (
                    <div
                        key={fingerprint}
                        className={`grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2 border-b border-primary px-2 py-1.5 ${
                            isActive ? 'bg-primary-highlight' : 'hover:bg-primary-highlight'
                        }`}
                        data-attr="error-tracking-manage-fingerprint-row"
                    >
                        <LemonCheckbox
                            checked={selected.includes(fingerprint)}
                            onChange={() => onToggle(fingerprint)}
                            label={<span className="sr-only">Select {accessibleLabel}</span>}
                            data-attr="error-tracking-manage-fingerprint-select"
                        />
                        <LemonButton
                            aria-pressed={isActive}
                            type="tertiary"
                            size="xsmall"
                            fullWidth
                            noPadding
                            className="min-w-0 justify-start text-xs"
                            onClick={() => onActivate(fingerprint)}
                            data-attr="error-tracking-manage-fingerprint-preview"
                        >
                            <FingerprintLabel fingerprint={fingerprint} sample={sample} />
                        </LemonButton>
                        <span className="text-xs tabular-nums text-muted">
                            {dayjs(created_at).tz(timezone).format('D MMM')}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}
