import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInputSelect,
    LemonModal,
    LemonSkeleton,
} from '@posthog/lemon-ui'

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

function LinearMirrorTeamSelect({
    integrationId,
    disabled,
    value,
    onChange,
}: {
    integrationId: number
    disabled?: boolean
    value?: string | null
    onChange?: (value: string | null) => void
}): JSX.Element {
    const { options, loading } = useLinearTeams(integrationId)
    return (
        <LemonInputSelect
            mode="single"
            value={value ? [value] : []}
            onChange={(next) => onChange?.(next[0] ?? null)}
            options={options}
            loading={loading}
            disabled={disabled}
            placeholder="Select a team"
            data-attr="select-linear-mirror-team"
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
    const mirrorError =
        typeof linearTeamsValidationErrors.mirrorTeamId === 'string'
            ? linearTeamsValidationErrors.mirrorTeamId
            : undefined

    // A radio group disables per option, so the saving reason goes on each one.
    const scopeOptions = isLinearIssuesToggling
        ? SCOPE_OPTIONS.map((option) => ({ ...option, disabledReason: 'Saving' }))
        : SCOPE_OPTIONS

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Linear"
            description="Choose which Linear teams self-driving reads, and whether new reports open Linear issues."
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
                        disabledReason={scopeError ?? mirrorError}
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
                    <LemonDivider className="my-1" />
                    <LemonField
                        name="mirrorReports"
                        help="Applies to reports that reach your inbox from now on. Each issue gets the report's title, summary, and a link back, and resolving or deleting the report closes it. Skipped while self-driving settings name an issue tracker for pull requests."
                    >
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                checked={value}
                                onChange={onChange}
                                disabledReason={isLinearIssuesToggling ? 'Saving' : undefined}
                                label="Open a Linear issue for each new report"
                                data-attr="signal-source-linear-mirror-reports"
                            />
                        )}
                    </LemonField>
                    {linearTeams.mirrorReports &&
                        (integrationsUnknown ? (
                            <LemonSkeleton className="h-10" />
                        ) : linearIntegration ? (
                            <LemonField name="mirrorTeamId" label="Team for new issues">
                                <LinearMirrorTeamSelect
                                    integrationId={linearIntegration.id}
                                    disabled={isLinearIssuesToggling}
                                />
                            </LemonField>
                        ) : linearTeams.scope === 'selected' ? null : (
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
