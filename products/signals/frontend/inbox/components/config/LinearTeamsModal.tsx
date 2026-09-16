import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonBanner, LemonButton, LemonInputSelect, LemonModal } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { useLinearTeams } from 'lib/integrations/LinearIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { LinearTeamsModalLogicProps, LinearTeamsScope, linearTeamsModalLogic } from '../../logics/linearTeamsModalLogic'
import { SignalSourceConfig } from '../../types'

const SCOPE_OPTIONS: LemonRadioOption<LinearTeamsScope>[] = [
    { value: 'all', label: 'All teams', 'data-attr': 'signal-source-linear-teams-all' },
    { value: 'selected', label: 'Only the teams I pick', 'data-attr': 'signal-source-linear-teams-selected' },
]

export interface LinearTeamsModalProps {
    config: SignalSourceConfig | null
    enableOnSave: boolean
    viaSetupWizard: boolean
    onClose: () => void
}

function LinearTeamsSelect({
    integrationId,
    value,
    onChange,
}: {
    integrationId: number
    value?: string[]
    onChange?: (value: string[]) => void
}): JSX.Element {
    const { options, loading } = useLinearTeams(integrationId)
    return (
        <LemonInputSelect
            mode="multiple"
            value={value ?? []}
            onChange={onChange}
            options={options}
            loading={loading}
            placeholder="Select teams"
            data-attr="select-linear-teams"
        />
    )
}

export function LinearTeamsModal({
    config,
    enableOnSave,
    viaSetupWizard,
    onClose,
}: LinearTeamsModalProps): JSX.Element {
    const formId = useId()
    const logicProps: LinearTeamsModalLogicProps = { config, enableOnSave, viaSetupWizard, onClose }
    const logic = linearTeamsModalLogic(logicProps)
    const { linearTeams, linearTeamsValidationErrors, isLinearIssuesToggling } = useValues(logic)
    const { linearIntegrations } = useValues(integrationsLogic)
    // The warehouse source that feeds this signal source needs a Linear connection, so one exists
    // in practice; the first one is used when a project has connected more than one workspace.
    const integration = linearIntegrations[0] ?? null

    const handleClose = (): void => {
        if (isLinearIssuesToggling) {
            return
        }
        onClose()
    }

    const scopeError =
        typeof linearTeamsValidationErrors.scope === 'string' ? linearTeamsValidationErrors.scope : undefined

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Linear teams"
            description="Choose which Linear teams self-driving reads. It reads open issues only from those teams."
            width={480}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={isLinearIssuesToggling ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form={formId}
                        htmlType="submit"
                        loading={isLinearIssuesToggling}
                        disabledReason={scopeError}
                        data-attr="signal-source-linear-teams-save"
                    >
                        {enableOnSave && !config?.enabled ? 'Turn on Linear' : 'Save'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={linearTeamsModalLogic} props={logicProps} formKey="linearTeams" id={formId} enableFormOnSubmit>
                <div className="flex flex-col gap-3">
                    <LemonField name="scope">
                        {({ value, onChange }) => (
                            <LemonRadio
                                value={value}
                                onChange={onChange}
                                options={SCOPE_OPTIONS}
                                aria-label="Which Linear teams to read"
                            />
                        )}
                    </LemonField>
                    {linearTeams.scope === 'selected' &&
                        (integration ? (
                            <LemonField
                                name="teamIds"
                                help="Applies from the next sync. Reports already in your inbox stay."
                            >
                                <LinearTeamsSelect integrationId={integration.id} />
                            </LemonField>
                        ) : (
                            <LemonBanner type="warning">
                                Couldn't find your Linear connection, so the team list isn't available. Reconnect Linear
                                in integration settings, then try again.
                            </LemonBanner>
                        ))}
                </div>
            </Form>
        </LemonModal>
    )
}
