import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { GuidedWizardStep, GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import { ImportWizardStep, customerIOImportLogic } from './customerIOImportLogic'
import { ChooseDataStep } from './steps/ChooseDataStep'
import { ConnectStep } from './steps/ConnectStep'
import { ImportProgressStep } from './steps/ImportProgressStep'
import { ProviderStep } from './steps/ProviderStep'
import { SyncStep } from './steps/SyncStep'

const STEPS: GuidedWizardStep<ImportWizardStep>[] = [
    { step: 'provider', label: 'Choose a tool', dataAttr: 'messaging-import-step-provider' },
    { step: 'connect', label: 'Connect', dataAttr: 'messaging-import-step-connect' },
    { step: 'choose', label: 'Choose data', dataAttr: 'messaging-import-step-choose' },
    { step: 'import', label: 'Import', dataAttr: 'messaging-import-step-import' },
    { step: 'sync', label: 'Keep in sync', optional: true, dataAttr: 'messaging-import-step-sync' },
]

const STEP_CONTENT: Record<ImportWizardStep, () => JSX.Element> = {
    provider: ProviderStep,
    connect: ConnectStep,
    choose: ChooseDataStep,
    import: ImportProgressStep,
    sync: SyncStep,
}

export function ImportWizard(): JSX.Element {
    useMountedLogic(customerIOImportLogic)
    const { currentStep, disabledSteps, syncConfig, syncConfigLoading, importRuns, importRunsLoading } =
        useValues(customerIOImportLogic)
    const { setStep, loadSyncConfig, loadImportRuns } = useActions(customerIOImportLogic)
    const StepContent = STEP_CONTENT[currentStep]

    const content =
        (syncConfig === null && syncConfigLoading) || (importRuns === null && importRunsLoading) ? (
            <div className="flex justify-center py-8">
                <Spinner className="text-3xl" />
            </div>
        ) : syncConfig === null || importRuns === null ? (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => {
                        loadSyncConfig()
                        loadImportRuns()
                    },
                }}
            >
                Couldn't load your imports.
            </LemonBanner>
        ) : (
            <>
                <GuidedWizardStepper
                    steps={STEPS}
                    currentStep={currentStep}
                    onStepClick={setStep}
                    disabledSteps={disabledSteps}
                    className="flex-wrap"
                    aria-label="Import progress"
                />
                <StepContent />
            </>
        )

    return (
        <div className="space-y-4" data-attr="messaging-import-wizard">
            <div>
                <h2 className="text-xl font-semibold mb-1">Import</h2>
                <p className="text-sm text-secondary m-0">
                    Bring subscription topics, opt-outs and suppressed addresses over from another messaging tool. See
                    the{' '}
                    <Link to="https://posthog.com/docs/workflows/import-customerio-optouts" target="_blank">
                        Customer.io import guide
                    </Link>{' '}
                    for details.
                </p>
            </div>
            {content}
        </div>
    )
}
