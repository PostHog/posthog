import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { FingerprintExceptionPane } from './FingerprintExceptionPane'
import { ManageFingerprintsList } from './ManageFingerprintsList'
import { manageFingerprintsLogic } from './manageFingerprintsLogic'

export function ManageFingerprintsModal({ issueId }: { issueId: string }): JSX.Element {
    const {
        isOpen,
        selected,
        unmerging,
        unmergeDisabledReason,
        issueFingerprints,
        issueFingerprintsLoading,
        samples,
        activeFingerprint,
        activeEvent,
        activeEventLoading,
        activeEventError,
    } = useValues(manageFingerprintsLogic({ issueId }))
    const { closeManage, toggleFingerprint, setActiveFingerprint, unmergeSelected, retryActiveEvent } = useActions(
        manageFingerprintsLogic({ issueId })
    )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeManage}
            closable={!unmerging}
            title="Manage fingerprints"
            description="Unmerge fingerprints into separate issues. Each fingerprint you unmerge becomes its own issue."
            width={960}
            data-attr="error-tracking-manage-fingerprints-modal"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={closeManage}
                        disabledReason={unmerging ? 'Wait for unmerging to finish' : null}
                        data-attr="error-tracking-manage-fingerprints-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        loading={unmerging}
                        disabledReason={unmergeDisabledReason}
                        onClick={unmergeSelected}
                        data-attr="error-tracking-unmerge-fingerprints"
                    >
                        {selected.length > 1 ? `Unmerge ${selected.length} fingerprints` : 'Unmerge'}
                    </LemonButton>
                </>
            }
        >
            <div className="@container/manage-fingerprints overflow-hidden rounded border border-primary">
                <div className="grid h-96 grid-cols-1 grid-rows-2 divide-y divide-primary @3xl/manage-fingerprints:grid-cols-[18rem_minmax(0,1fr)] @3xl/manage-fingerprints:grid-rows-1 @3xl/manage-fingerprints:divide-x @3xl/manage-fingerprints:divide-y-0">
                    <ManageFingerprintsList
                        loading={issueFingerprintsLoading}
                        fingerprints={issueFingerprints}
                        samples={samples}
                        selected={selected}
                        activeFingerprint={activeFingerprint}
                        onToggle={toggleFingerprint}
                        onActivate={setActiveFingerprint}
                    />
                    <FingerprintExceptionPane
                        issueId={issueId}
                        activeFingerprint={activeFingerprint}
                        event={activeEvent}
                        loading={activeEventLoading}
                        error={activeEventError}
                        onRetry={retryActiveEvent}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
