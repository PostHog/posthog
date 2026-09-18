import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'
import { Spinner, Text } from 'lib/ui/quill'

import { FingerprintRow } from './FingerprintRow'
import { FingerprintSampleMap } from './fingerprintSamplesLogic'

interface FingerprintListProps {
    fingerprints: ErrorTrackingFingerprint[]
    samples: FingerprintSampleMap
    loading: boolean
    onSelect: (fingerprint: string) => void
    onFindSimilar: (fingerprint: string, firstSeen: string) => void
}

export function FingerprintList({
    fingerprints,
    samples,
    loading,
    onSelect,
    onFindSimilar,
}: FingerprintListProps): JSX.Element {
    if (loading) {
        return (
            <div className="flex min-h-0 flex-1 items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (fingerprints.length === 0) {
        return (
            <div className="flex min-h-0 flex-1 items-center justify-center text-center">
                <Text variant="muted">No fingerprints found for this issue.</Text>
            </div>
        )
    }

    return (
        <>
            <div className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto">
                {fingerprints.map(({ fingerprint, created_at }) => (
                    <FingerprintRow
                        key={fingerprint}
                        fingerprint={fingerprint}
                        firstSeen={created_at}
                        sample={samples[fingerprint]}
                        onSelect={() => onSelect(fingerprint)}
                        onFindSimilar={() => onFindSimilar(fingerprint, created_at)}
                    />
                ))}
            </div>
            <Text size="xs" variant="muted" className="pt-1 text-center">
                Select a fingerprint to filter exceptions.
            </Text>
        </>
    )
}
