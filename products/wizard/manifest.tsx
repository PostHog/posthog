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
    treeItemsProducts: [],
}
