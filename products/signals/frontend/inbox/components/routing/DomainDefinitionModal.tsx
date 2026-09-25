import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { inboxRoutingLogic } from '../../logics/inboxRoutingLogic'

export function DomainDefinitionModal({ projectId }: { projectId: string }): JSX.Element {
    const logic = inboxRoutingLogic({ projectId })
    const { catalogue, domainVisible, domainDraft, editingDomainId, savedDomainLoading, error } = useValues(logic)
    const { closeDomain, setDomainDraft, saveDomain } = useActions(logic)
    return (
        <LemonModal
            isOpen={domainVisible}
            onClose={closeDomain}
            title={editingDomainId ? 'Edit product domain' : 'Add product domain'}
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeDomain}
                        disabledReason={savedDomainLoading ? 'Saving domain' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveDomain}
                        loading={savedDomainLoading}
                        disabledReason={!domainDraft.name.trim() ? 'Enter a name' : undefined}
                        data-attr="inbox-domain-save"
                    >
                        Save domain
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                {error && <LemonBanner type="error">{error}</LemonBanner>}
                <p className="m-0">
                    Define the capability that needs fixing, including what belongs elsewhere. This definition is shared
                    with your project.
                </p>
                <label className="flex flex-col gap-1">
                    <span>Name</span>
                    <LemonInput
                        value={domainDraft.name}
                        maxLength={100}
                        onChange={(name) => setDomainDraft({ name })}
                        disabled={savedDomainLoading}
                        data-attr="inbox-domain-name"
                    />
                </label>
                <label className="flex flex-col gap-1">
                    <span>Responsibilities and boundaries</span>
                    <LemonTextArea
                        value={domainDraft.description}
                        maxLength={4000}
                        onChange={(description) => setDomainDraft({ description })}
                        disabled={savedDomainLoading}
                    />
                </label>
                <label className="flex flex-col gap-1">
                    <span>Responsible team</span>
                    <LemonSelect
                        value={domainDraft.owning_role_id ?? null}
                        onChange={(owning_role_id) => setDomainDraft({ owning_role_id })}
                        disabled={savedDomainLoading}
                        options={[
                            { value: null, label: 'No team' },
                            ...(catalogue?.teams.map((team) => ({ value: team.id, label: team.name })) ?? []),
                        ]}
                    />
                </label>
                {editingDomainId && (
                    <LemonCheckbox
                        checked={!!domainDraft.archived}
                        onChange={(archived) => setDomainDraft({ archived })}
                        label="Archive this domain. Keep its history and personal rules."
                        disabled={savedDomainLoading}
                    />
                )}
            </div>
        </LemonModal>
    )
}
