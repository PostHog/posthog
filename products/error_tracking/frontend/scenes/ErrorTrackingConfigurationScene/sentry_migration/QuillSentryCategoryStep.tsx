import { useActions, useValues } from 'kea'

import { Button, CardGroup } from '@posthog/quill'

import { QuillImportWizardStepActions } from './QuillImportWizardStepActions'
import { QuillImportWizardStepHeading } from './QuillImportWizardStepHeading'
import { QuillSentryMigrationItemCard } from './QuillSentryMigrationItemCard'
import type { SentryCategoryStepProps } from './SentryCategoryStep'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { itemDisabledReason } from './sentryMigrationSelection'

export function QuillSentryCategoryStep({ category }: SentryCategoryStepProps): JSX.Element {
    const { items, selectedItemIds } = useValues(sentryMigrationLogic)
    const { toggleItem, goToNextStep, goToPreviousStep } = useActions(sentryMigrationLogic)
    const categoryItems = (items ?? []).filter((item) => item.category === category.category)

    return (
        <>
            <QuillImportWizardStepHeading title={category.title} description={category.description} />
            <CardGroup size="sm">
                {categoryItems.map((item) => (
                    <QuillSentryMigrationItemCard
                        key={item.id}
                        item={item}
                        selected={selectedItemIds.includes(item.id)}
                        disabledReason={itemDisabledReason(item)}
                        onToggle={() => toggleItem(item.id)}
                    />
                ))}
            </CardGroup>
            <QuillImportWizardStepActions onBack={goToPreviousStep}>
                <Button variant="primary" onClick={goToNextStep} data-attr="error-tracking-import-next">
                    Continue
                </Button>
            </QuillImportWizardStepActions>
        </>
    )
}
