import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { ImportStepFooter } from '../components/ImportStepFooter'
import { customerIOImportLogic } from '../customerIOImportLogic'

export function ChooseDataStep(): JSX.Element {
    const {
        importStepOptions,
        deselectedImportSteps,
        selectedImportSteps,
        importError,
        hasStoredKey,
        startedImportRunLoading,
    } = useValues(customerIOImportLogic)
    const { toggleImportStep, submitImportForm, startImport } = useActions(customerIOImportLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                {importStepOptions.map((step) => (
                    <div key={step.key}>
                        <LemonCheckbox
                            checked={!deselectedImportSteps.includes(step.key)}
                            onChange={() => toggleImportStep(step.key)}
                            label={step.label}
                            data-attr={`customerio-import-step-${step.key}`}
                        />
                        <div className="text-xs text-secondary ml-6">{step.description}</div>
                    </div>
                ))}
            </div>
            <p className="text-sm text-secondary m-0">
                Running the import again is safe. It updates existing categories and people instead of adding them
                twice. After the import, you can also upload subscription preferences from a CSV.
            </p>
            {importError && (
                <LemonBanner type="error" className="text-sm">
                    {importError}
                </LemonBanner>
            )}
            <ImportStepFooter>
                <LemonButton
                    type="primary"
                    onClick={() => (hasStoredKey ? startImport({ apiKey: null }) : submitImportForm())}
                    loading={startedImportRunLoading}
                    disabledReason={
                        selectedImportSteps.length === 0 ? 'Select at least one thing to import' : undefined
                    }
                    data-attr="customerio-import-start"
                >
                    Start import
                </LemonButton>
            </ImportStepFooter>
        </div>
    )
}
