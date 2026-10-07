import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { broadcastAudienceListLogic } from './broadcastAudienceListLogic'

/** Turns an uploaded CSV into the broadcast's whole audience: one email per row. */
export function BroadcastAudienceListModal(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastAudienceListLogic(props)
    const { isListModalOpen, file, creating, createError, submitDisabledReason } = useValues(logic)
    const { closeListModal, setFile, submitList } = useActions(logic)

    return (
        <LemonModal
            isOpen={isListModalOpen}
            onClose={creating ? undefined : closeListModal}
            title="Upload a list"
            description="The list is saved with this broadcast and replaces its other audience conditions."
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeListModal}
                        disabledReason={creating ? 'Saving the list' : null}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitList}
                        loading={creating}
                        disabledReason={submitDisabledReason}
                        data-attr="broadcast-audience-list-submit"
                    >
                        Add to audience
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4" data-attr="broadcast-audience-list-modal">
                <span className="text-sm text-secondary">
                    Every row gets one email, including people who aren't in PostHog yet. The file needs an{' '}
                    <code>email</code> column. You can use any other column in the email, for example{' '}
                    <code>{'{{ variables.org_name }}'}</code>. Add a <code>distinct_id</code> column to match rows to
                    people.
                </span>
                <LemonFileInput
                    accept=".csv"
                    multiple={false}
                    value={file ? [file] : []}
                    onChange={(files) => setFile(files[0] ?? null)}
                    disabledReason={creating ? 'Saving the list' : null}
                />
                {createError ? <LemonBanner type="error">{createError}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
