import { useActions, useValues } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { QuillImportWizardStepActions } from './QuillImportWizardStepActions'
import { QuillImportWizardStepHeading } from './QuillImportWizardStepHeading'
import { describeImportPlan, importButtonLabel } from './sentryMigrationFormat'
import { importSummary, sentryMigrationLogic } from './sentryMigrationLogic'

export function QuillSentryReviewStep(): JSX.Element {
    const { importPlan, importResult, importResultLoading, selectedItemIds } = useValues(sentryMigrationLogic)
    const { applyImport, goToPreviousStep, resetWizard } = useActions(sentryMigrationLogic)
    const editAccessDisabledReason = errorTrackingEditAccessDisabledReason()
    const changes = describeImportPlan(importPlan)

    return (
        <>
            <QuillImportWizardStepHeading
                title="Review and import"
                description="Check what changes in PostHog. You can change or remove anything you import later, on this page."
            />
            {importResult && (
                <Item tone="success" size="sm">
                    <ItemContent>
                        <ItemDescription>{importSummary(importResult)}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="outline"
                            onClick={resetWizard}
                            data-attr="error-tracking-import-another-project"
                        >
                            Import another project
                        </Button>
                    </ItemActions>
                </Item>
            )}
            {changes.length > 0 ? (
                <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
                    {changes.map((change) => (
                        <Text key={change} size="xs" render={<li />}>
                            {change}
                        </Text>
                    ))}
                </ul>
            ) : !importResult ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Nothing is selected. Go back and select the settings you want to import.
                </Text>
            ) : null}
            <QuillImportWizardStepActions onBack={goToPreviousStep}>
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
                    {importButtonLabel(selectedItemIds.length)}
                </Button>
            </QuillImportWizardStepActions>
        </>
    )
}
