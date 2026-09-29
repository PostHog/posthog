import { useActions, useMountedLogic, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonFileInput,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { broadcastAudienceListLogic } from './broadcastAudienceListLogic'

function PastedListSummary(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const { pastedList } = useValues(broadcastAudienceListLogic(props))
    const { entries, idType, duplicatesRemoved } = pastedList

    if (entries.length === 0) {
        return <span>One email address or distinct ID per line. Commas work too.</span>
    }
    return (
        <span>
            {humanFriendlyNumber(entries.length)} {idType === 'email' ? 'email addresses' : 'distinct IDs'}
            {duplicatesRemoved > 0
                ? `, ${humanFriendlyNumber(duplicatesRemoved)} ${duplicatesRemoved === 1 ? 'duplicate' : 'duplicates'} removed`
                : null}
        </span>
    )
}

/** Turns a pasted or uploaded list of people into a static cohort and adds it to the broadcast's audience. */
export function BroadcastAudienceListModal(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const logic = broadcastAudienceListLogic(props)
    const { isListModalOpen, source, pastedText, file, cohortName, creating, createError, submitDisabledReason } =
        useValues(logic)
    const { audienceProperties } = useValues(broadcastWizardLogic)
    const { closeListModal, setSource, setPastedText, setFile, setCohortName, createListCohort } = useActions(logic)

    return (
        <LemonModal
            isOpen={isListModalOpen}
            onClose={creating ? undefined : closeListModal}
            title="Add people from a list"
            description="The list is saved as a cohort, so you can reuse it in other broadcasts."
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
                <LemonSegmentedButton
                    fullWidth
                    value={source}
                    onChange={setSource}
                    options={[
                        { value: 'paste', label: 'Paste a list', 'data-attr': 'broadcast-audience-list-paste' },
                        { value: 'upload', label: 'Upload a CSV', 'data-attr': 'broadcast-audience-list-upload' },
                    ]}
                />
                {source === 'paste' ? (
                    <div className="flex flex-col gap-1">
                        <LemonTextArea
                            value={pastedText}
                            onChange={setPastedText}
                            minRows={6}
                            maxRows={12}
                            placeholder={'ada@example.com\ngrace@example.com'}
                            autoFocus
                            data-attr="broadcast-audience-list-textarea"
                        />
                        <div className="text-xs text-secondary">
                            <PastedListSummary />
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-col gap-1">
                        <LemonFileInput
                            accept=".csv"
                            multiple={false}
                            value={file ? [file] : []}
                            onChange={(files) => setFile(files[0] ?? null)}
                            showUploadedFiles={false}
                            callToAction={
                                <div
                                    className={cn(
                                        'flex w-full flex-col items-center justify-center gap-1 rounded border border-dashed p-6',
                                        file && 'border-success'
                                    )}
                                >
                                    <IconUpload className="text-2xl text-secondary" />
                                    <div className="font-semibold">
                                        {file ? file.name : 'Drop a CSV here or click to choose one'}
                                    </div>
                                </div>
                            }
                        />
                        <div className="text-xs text-secondary">
                            Needs a column named <code>email</code>, <code>distinct_id</code> or <code>person_id</code>.
                            A single column without a header is read as distinct IDs.
                        </div>
                    </div>
                )}
                <LemonInput
                    value={cohortName}
                    onChange={setCohortName}
                    placeholder="Cohort name"
                    fullWidth
                    data-attr="broadcast-audience-list-name"
                    prefix={<span className="text-secondary">Cohort name</span>}
                />
                <div className="text-xs text-secondary">
                    Only people who are already in PostHog are included. Anyone else on the list won't receive the
                    email.
                    {audienceProperties.length > 0
                        ? ' People must be on every list and match your other conditions to get the email.'
                        : null}
                </div>
                {createError ? <LemonBanner type="error">{createError}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
