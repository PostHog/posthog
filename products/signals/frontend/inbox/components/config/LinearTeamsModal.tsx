import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonBanner, LemonButton, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { LinearTeamsModalLogicProps, linearTeamsModalLogic } from '../../logics/linearTeamsModalLogic'
import { LINEAR_TEAMS_REQUIRED, SignalSourceConfig, sourceFilterIsSet } from '../../types'
import { LinearTeamsSelect } from './LinearTeamsSelect'

export interface LinearTeamsModalProps {
    config: SignalSourceConfig | null
    enableOnSave: boolean
    viaSetupWizard: boolean
    onUseFilter?: () => void
    onClose: () => void
}

export function LinearTeamsModal({
    config,
    enableOnSave,
    viaSetupWizard,
    onUseFilter,
    onClose,
}: LinearTeamsModalProps): JSX.Element {
    const formId = useId()
    const logicProps: LinearTeamsModalLogicProps = { config, enableOnSave, viaSetupWizard, onClose }
    const logic = linearTeamsModalLogic(logicProps)
    const { isLinearTeamsValid, isLinearIssuesToggling, linearIntegration, integrationsUnknown } = useValues(logic)

    const handleClose = (): void => {
        if (isLinearIssuesToggling) {
            return
        }
        onClose()
    }

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Linear teams"
            description={
                sourceFilterIsSet(config?.config)
                    ? 'Choose teams to narrow your saved filter. Leave empty to apply the filter across all teams.'
                    : 'Which Linear issues should Self-driving respond to? Select the teams whose open issues you want it to read.'
            }
            width={480}
            footer={
                <>
                    {onUseFilter && (
                        <LemonButton
                            type="tertiary"
                            onClick={onUseFilter}
                            disabledReason={isLinearIssuesToggling ? 'Saving' : undefined}
                        >
                            Use an issue filter
                        </LemonButton>
                    )}
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
                        disabledReason={isLinearTeamsValid ? undefined : LINEAR_TEAMS_REQUIRED}
                        data-attr="signal-source-linear-teams-save"
                    >
                        {enableOnSave && !config?.enabled ? 'Turn on Linear' : 'Save'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={linearTeamsModalLogic} props={logicProps} formKey="linearTeams" id={formId} enableFormOnSubmit>
                {integrationsUnknown ? (
                    <LemonSkeleton className="h-10" />
                ) : linearIntegration ? (
                    <LemonField
                        name="teamIds"
                        label="Teams"
                        help="Applies from the next sync. Reports already in your inbox stay."
                    >
                        <LinearTeamsSelect integrationId={linearIntegration.id} disabled={isLinearIssuesToggling} />
                    </LemonField>
                ) : (
                    <LemonBanner type="warning">
                        Couldn't find your Linear connection, so the team list isn't available. Reconnect Linear in
                        integration settings, then try again.
                    </LemonBanner>
                )}
            </Form>
        </LemonModal>
    )
}
