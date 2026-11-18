import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonBanner, LemonButton, LemonInputSelect, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

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
    disabled,
    value,
    onChange,
}: {
    integrationId: number
    disabled?: boolean
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
            disabled={disabled}
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
    const { linearTeams, linearTeamsValidationErrors, isLinearIssuesToggling, linearIntegration, integrationsUnknown } =
        useValues(logic)

    const handleClose = (): void => {
        if (isLinearIssuesToggling) {
            return
        }
        onClose()
    }

    const scopeError =
        typeof linearTeamsValidationErrors.scope === 'string' ? linearTeamsValidationErrors.scope : undefined

    // A radio group disables per option, so the saving reason goes on each one.
    const scopeOptions = isLinearIssuesToggling
        ? SCOPE_OPTIONS.map((option) => ({ ...option, disabledReason: 'Saving' }))
        : SCOPE_OPTIONS

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
                                options={scopeOptions}
                                aria-label="Which Linear teams to read"
                            />
                        )}
                    </LemonField>
                    {linearTeams.scope === 'selected' &&
                        (integrationsUnknown ? (
                            <LemonSkeleton className="h-10" />
                        ) : linearIntegration ? (
                            <LemonField
                                name="teamIds"
                                help="Applies from the next sync. Reports already in your inbox stay."
                            >
                                <LinearTeamsSelect
                                    integrationId={linearIntegration.id}
                                    disabled={isLinearIssuesToggling}
                                />
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
