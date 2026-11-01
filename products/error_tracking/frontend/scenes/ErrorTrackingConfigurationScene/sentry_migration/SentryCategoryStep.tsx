import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

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
            <div className="rounded border bg-surface-primary divide-y">
                {categoryItems.map((item) => (
                    <SentryMigrationItemCard
                        key={item.id}
                        item={item}
                        selected={selectedItemIds.includes(item.id)}
                        disabledReason={itemDisabledReason(item)}
                        onToggle={() => toggleItem(item.id)}
                    />
                ))}
            </div>
            <ImportWizardStepActions onBack={goToPreviousStep}>
                <LemonButton type="primary" onClick={goToNextStep} data-attr="error-tracking-import-next">
                    Continue
                </LemonButton>
            </ImportWizardStepActions>
        </>
    )
}
