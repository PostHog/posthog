import { FEATURE_FLAGS } from 'lib/constants'

import { ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Wizard',
    scenes: {
        WizardRuns: {
            import: () => import('./frontend/WizardRunsScene'),
            projectBased: true,
            name: 'Wizard runs',
            description: 'Run the setup agent in the cloud, then review the changes it produces.',
            layout: 'app-container',
            iconType: 'llm_prompts',
        },
    },
    routes: {
        '/wizard/runs': ['WizardRuns', 'wizardRuns'],
    },
    redirects: {},
    urls: {
        wizardRuns: (): string => '/wizard/runs',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Wizard',
            intents: [],
            category: ProductItemCategory.TOOLS,
            type: 'wizard',
            iconType: 'wizard',
            iconColor: ['var(--color-product-wizard-light)', 'var(--color-product-wizard-dark)'],
            href: '/wizard/runs',
            flag: FEATURE_FLAGS.WIZARD_UI_ENABLED,
            sceneKey: 'WizardRuns',
        },
    ],
}
