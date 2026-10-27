import { useActions, useValues } from 'kea'

import { Button, CardGroup } from '@posthog/quill'

import { ImportWizardStepActions } from './ImportWizardStepActions'
import { ImportWizardStepHeading } from './ImportWizardStepHeading'
import { SentryMigrationItemCard } from './SentryMigrationItemCard'
import { sentryMigrationLogic } from './sentryMigrationLogic'
import { itemDisabledReason } from './sentryMigrationSelection'
import type { ImportCategory } from './sentryMigrationSteps'

export interface SentryCategoryStepProps {
    category: ImportCategory
}

export function SentryCategoryStep({ category }: SentryCategoryStepProps): JSX.Element {
    const { items, selectedItemIds } = useValues(sentryMigrationLogic)
    const { toggleItem, goToNextStep, goToPreviousStep } = useActions(sentryMigrationLogic)
    const categoryItems = (items ?? []).filter((item) => item.category === category.category)

    return (
        <>
            <ImportWizardStepHeading title={category.title} description={category.description} />
            <CardGroup size="sm">
                {categoryItems.map((item) => (
                    <SentryMigrationItemCard
                        key={item.id}
                        item={item}
                        selected={selectedItemIds.includes(item.id)}
                        disabledReason={itemDisabledReason(item)}
                        onToggle={() => toggleItem(item.id)}
                    />
                ))}
            </CardGroup>
            <ImportWizardStepActions onBack={goToPreviousStep}>
                <Button variant="primary" onClick={goToNextStep} data-attr="error-tracking-import-next">
                    Continue
                </Button>
            </ImportWizardStepActions>
        </>
    )
}
