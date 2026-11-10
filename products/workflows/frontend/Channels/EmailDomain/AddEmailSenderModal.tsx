import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { addEmailSenderLogic } from './addEmailSenderLogic'

export function AddEmailSenderModal(): JSX.Element {
    const {
        isOpen,
        domains,
        selectedDomain,
        senderName,
        localPart,
        submitDisabledReason,
        submitError,
        addedSenderLoading,
    } = useValues(addEmailSenderLogic)
    const {
        closeAddSender,
        selectDomain,
        setSenderNameInput,
        setLocalPart,
        addSender,
        useNewDomain,
        finishVerification,
    } = useActions(addEmailSenderLogic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeAddSender}
            title="Add a sender"
            description="Send email from another address on a domain you already set up."
            width={520}
            footer={
                <div className="flex flex-wrap items-center justify-between gap-2 w-full">
                    <LemonButton type="tertiary" onClick={useNewDomain} data-attr="email-sender-add-new-domain">
                        Use a new domain instead
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeAddSender}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={addSender}
                            loading={addedSenderLoading}
                            disabledReason={submitDisabledReason}
                            data-attr="email-sender-add-submit"
                        >
                            Add sender
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                {domains.length > 1 && (
                    <LemonField.Pure label="Domain">
                        <LemonSelect
                            fullWidth
                            value={selectedDomain?.domain ?? null}
                            onChange={(domain) => domain && selectDomain(domain)}
                            options={domains.map((candidate) => ({
                                value: candidate.domain,
                                label: candidate.domain,
                                labelInMenu: (
                                    <span className="flex items-center gap-2">
                                        {candidate.domain}
                                        {!candidate.verified && (
                                            <LemonTag type="warning" size="small">
                                                Unverified
                                            </LemonTag>
                                        )}
                                    </span>
                                ),
                            }))}
                            data-attr="email-sender-add-domain"
                        />
                    </LemonField.Pure>
                )}
                {selectedDomain && !selectedDomain.verified ? (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Finish verification',
                            onClick: finishVerification,
                            'data-attr': 'email-sender-add-finish-verification',
                        }}
                    >
                        {selectedDomain.domain} is not verified yet. Finish verifying it before you add senders to it.
                    </LemonBanner>
                ) : (
                    <>
                        <LemonField.Pure label="Sender name" help="Shown as the From name in the inbox.">
                            <LemonInput
                                value={senderName}
                                onChange={setSenderNameInput}
                                placeholder="Acme"
                                data-attr="email-sender-add-name"
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Address">
                            <LemonInput
                                value={localPart}
                                onChange={setLocalPart}
                                placeholder="hello"
                                autoFocus
                                suffix={<span className="text-secondary">@{selectedDomain?.domain}</span>}
                                onPressEnter={() => !submitDisabledReason && !addedSenderLoading && addSender()}
                                data-attr="email-sender-add-local-part"
                            />
                        </LemonField.Pure>
                    </>
                )}
                {submitError && <LemonBanner type="error">{submitError}</LemonBanner>}
            </div>
        </LemonModal>
    )
}
