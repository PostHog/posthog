import { IconCompass } from '@posthog/icons'

import { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { InvestigationPreview } from './InvestigationPreview'
import { investigationsSetupLogic } from './investigationsSetupLogic'
import { NewInvestigationButton } from './NewInvestigationButton'

export const investigationsEmptyState: SceneProductEmptyState = {
    statusLogic: investigationsSetupLogic,
    config: {
        productKey: ProductKey.INVESTIGATIONS,
        productName: 'Investigations',
        icon: <IconCompass />,
        accentColor: 'var(--color-product-investigations-light)',
        accentColorDark: 'var(--color-product-investigations-dark)',
        text: {
            'needs-setup': {
                headline: 'Find out why a metric changed',
                lead: 'Start with a question. Build SQL evidence with AI, test competing explanations, and keep the results behind your decision in one investigation.',
            },
        },
        PrimaryAction: NewInvestigationButton,
        previewLabel: 'Example: investigating a trial conversion change',
        Preview: InvestigationPreview,
        skippable: false,
    },
}
