import { useActions, useValues } from 'kea'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle, Text } from '@posthog/quill'

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
            {changes.length > 0 ? (
                <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
                    {changes.map((change) => (
                        <li key={change} className="text-sm">
                            {change}
                        </li>
                    ))}
                </ul>
            ) : importResult ? (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Import finished</EmptyTitle>
                        <EmptyDescription>{importSummary(importResult)}</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            onClick={resetWizard}
                            data-attr="error-tracking-import-another-project"
                        >
                            Import another project
                        </Button>
                    </EmptyContent>
                </Empty>
            ) : (
                <Text size="sm" variant="muted" className="m-0">
                    Nothing is selected. Go back and select the settings you want to import.
                </Text>
            )}
            <ImportWizardStepActions onBack={goToPreviousStep}>
                <Button
                    variant="primary"
                    onClick={applyImport}
                    loading={importResultLoading}
                    disabledReason={
                        editAccessDisabledReason ??
                        (changes.length === 0 ? 'Select at least one setting to import' : undefined)
                    }
                    data-attr="error-tracking-sentry-migration-import"
                >
                    {selectedItemIds.length === 1 ? 'Import 1 setting' : `Import ${selectedItemIds.length} settings`}
                </Button>
            </ImportWizardStepActions>
        </>
    )
}
