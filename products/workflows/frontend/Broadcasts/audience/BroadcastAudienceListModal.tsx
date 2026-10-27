import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CohortCsvDropzone } from 'scenes/cohorts/CohortCsvDropzone'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { broadcastAudienceListLogic } from './broadcastAudienceListLogic'

/** Turns an uploaded CSV of people into a static cohort and adds it to the broadcast's audience. */
export function BroadcastAudienceListModal(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastAudienceListLogic(props)
    const { isListModalOpen, file, cohortName, creating, createError, submitDisabledReason } = useValues(logic)
    const { audienceProperties } = useValues(broadcastWizardLogic)
    const { closeListModal, setFile, setCohortName, createListCohort } = useActions(logic)

    return (
        <LemonModal
            isOpen={isListModalOpen}
            onClose={creating ? undefined : closeListModal}
            title="Upload a list"
            description="The list is saved as a static cohort, so you can reuse it in other broadcasts."
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
                        onClick={createListCohort}
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
                    Each row creates or updates a person. The file needs an <code>email</code> column. Every other
                    column is saved on the person, so you can use it in the email, for example{' '}
                    <code>{'{{ person.properties.plan }}'}</code> for a <code>plan</code> column. Property names match
                    the column names exactly, including capital letters. To update people by their ID in your app, add a{' '}
                    <code>distinct_id</code> column, or an <code>id</code> column like a Customer.io export has.
                </span>
                <CohortCsvDropzone value={file} onChange={setFile} />
                <LemonInput
                    value={cohortName}
                    onChange={setCohortName}
                    placeholder="Cohort name"
                    fullWidth
                    data-attr="broadcast-audience-list-name"
                    prefix={<span className="text-secondary">Cohort name</span>}
                />
                <div className="text-xs text-secondary">
                    People who aren't in PostHog yet are created. A column with the same name as an existing property
                    replaces its value, and a blank cell leaves it as it is. Each row is sent as one event, so it counts
                    toward your event usage and triggers any destinations that run on all events.
                    {audienceProperties.length > 0
                        ? ' People must be on every list and match your other conditions to get the email.'
                        : null}
                </div>
                {createError ? <LemonBanner type="error">{createError}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
