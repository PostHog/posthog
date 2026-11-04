import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { ImportWizardStepActions } from './ImportWizardStepActions'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { formatRateLimit } from './sentryMigrationFormat'
import { importSummary, sentryMigrationLogic } from './sentryMigrationLogic'

export function SentryReviewStep(): JSX.Element {
    const { importPlan, importResult, importResultLoading, selectedItemIds } = useValues(sentryMigrationLogic)
    const { applyImport, goToPreviousStep, resetWizard } = useActions(sentryMigrationLogic)
    const editAccessDisabledReason = errorTrackingEditAccessDisabledReason()

    const changes: string[] = []
    if (importPlan.rateLimit) {
        changes.push(`Sets the project rate limit to ${formatRateLimit(importPlan.rateLimit)}`)
    }
    if (importPlan.manualRuleCount > 0) {
        changes.push(
            `Creates ${importPlan.manualRuleCount} manual suppression ${importPlan.manualRuleCount === 1 ? 'rule' : 'rules'}`
        )
    }
    if (importPlan.automaticRuleNames.length > 0) {
        changes.push(`Turns on these automatic suppression rules: ${importPlan.automaticRuleNames.join(', ')}`)
    }

    return (
        <>
            <ImportWizardStepHeading
                title="Review and import"
                description="Check what changes in PostHog. You can change or remove anything you import later, on this page."
            />
            {importResult && (
                <LemonBanner
                    type="success"
                    action={{
                        children: 'Import another project',
                        onClick: resetWizard,
                        'data-attr': 'error-tracking-import-another-project',
                    }}
                >
                    {importSummary(importResult)}
                </LemonBanner>
            )}
            {changes.length > 0 ? (
                <ul className="list-disc pl-5 mb-0 flex flex-col gap-1">
                    {changes.map((change) => (
                        <li key={change} className="text-sm">
                            {change}
                        </li>
                    ))}
                </ul>
            ) : !importResult ? (
                <p className="text-sm text-secondary mb-0">
                    Nothing is selected. Go back and select the settings you want to import.
                </p>
            ) : null}
            <ImportWizardStepActions onBack={goToPreviousStep}>
                <LemonButton
                    type="primary"
                    onClick={applyImport}
                    loading={importResultLoading}
                    disabledReason={
                        editAccessDisabledReason ??
                        (changes.length === 0 ? 'Select at least one setting to import' : undefined)
                    }
                    data-attr="error-tracking-sentry-migration-import"
                >
                    {selectedItemIds.length === 0
                        ? 'Import'
                        : selectedItemIds.length === 1
                          ? 'Import 1 setting'
                          : `Import ${selectedItemIds.length} settings`}
                </LemonButton>
            </ImportWizardStepActions>
        </>
    )
}
