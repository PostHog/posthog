import { FileSystemIconType, ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Wizard',
    scenes: {
        WizardRuns: {
            import: () => import('./frontend/WizardRunsScene'),
            projectBased: true,
            name: 'Wizard runs',
            layout: 'app-container',
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
            category: ProductItemCategory.ANALYTICS,
            type: 'wizard',
            iconType: 'llm_prompts' as FileSystemIconType,
            href: '/wizard/runs',
            sceneKey: 'WizardRuns',
        },
    ],
}
