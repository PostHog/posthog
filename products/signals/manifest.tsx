import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Inbox',
    scenes: {
        Inbox: {
            name: 'Inbox',
            import: () => import('./frontend/InboxScene'),
            projectBased: true,
            description: 'Actionable reports from automated analysis of your product sessions and signals.',
            layout: 'app-raw-no-header',
        },
    },
    routes: {
        '/inbox': ['Inbox', 'inbox'],
    },
    redirects: {},
    urls: {
        inbox: (): string => '/inbox',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
