import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { FingerprintLabel } from './FingerprintLabel'
import { FingerprintSampleMap } from './fingerprintSamplesLogic'
import { SimilarFingerprint, similarFingerprintsLogic } from './similarFingerprintsLogic'

export function SimilarFingerprintsModal({
    issueId,
    samples,
}: {
    issueId: string
    samples: FingerprintSampleMap
}): JSX.Element {
    const { originFingerprint, similar, similarLoading } = useValues(similarFingerprintsLogic({ issueId }))
    const { closeSimilar } = useActions(similarFingerprintsLogic({ issueId }))

    return (
        <LemonModal
            isOpen={originFingerprint !== null}
            onClose={closeSimilar}
            title="Similar fingerprints"
            description="Fingerprints across this project whose exceptions embed close to this one."
            width={640}
        >
            {originFingerprint && (
                <div className="flex flex-col gap-3">
                    <div className="rounded border border-primary p-2 text-xs">
                        <FingerprintLabel fingerprint={originFingerprint} sample={samples[originFingerprint]} />
                    </div>
                    <SimilarFingerprintsList loading={similarLoading} similar={similar} currentIssueId={issueId} />
                </div>
            )}
        </LemonModal>
    )
}

function SimilarFingerprintsList({
    loading,
    similar,
    currentIssueId,
}: {
    loading: boolean
    similar: SimilarFingerprint[]
    currentIssueId: string
}): JSX.Element {
    if (loading) {
        return (
            <div className="flex h-40 items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (similar.length === 0) {
        return (
            <div className="flex h-40 flex-col items-center justify-center gap-1 text-center">
                <span className="text-muted">No similar fingerprints found.</span>
                <span className="text-xs text-muted">
                    Fingerprints appear here once their exceptions have been embedded.
                </span>
            </div>
        )
    }

    return (
        <div className="flex max-h-96 flex-col gap-px overflow-y-auto">
            {similar.map(({ fingerprint, similarity, issueId, sample }) => (
                <div
                    key={fingerprint}
                    className="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-x-3 rounded px-2 py-1.5 hover:bg-primary-highlight"
                    data-attr="error-tracking-similar-fingerprint"
                >
                    <span className="text-sm font-semibold tabular-nums">{similarity}%</span>
                    <span className="min-w-0 text-xs">
                        <FingerprintLabel fingerprint={fingerprint} sample={sample} />
                    </span>
                    {issueId && issueId !== currentIssueId ? (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            to={urls.errorTrackingIssue(issueId)}
                            targetBlank
                            data-attr="error-tracking-similar-fingerprint-issue"
                        >
                            View issue
                        </LemonButton>
                    ) : (
                        <span className="text-xs text-muted">This issue</span>
                    )}
                </div>
            ))}
        </div>
    )
}
