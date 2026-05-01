import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'LegalDocuments',
    scenes: {
        LegalDocuments: {
            name: 'Legal documents',
            import: () => import('./frontend/scenes/LegalDocumentsScene'),
            organizationBased: true,
            activityScope: 'LegalDocument',
            description: 'Generate a Business Associate Agreement or Data Processing Agreement for your organization.',
        },
        LegalDocumentNew: {
            name: 'New legal document',
            import: () => import('./frontend/scenes/LegalDocumentNewScene'),
            organizationBased: true,
            activityScope: 'LegalDocument',
        },
    },
    routes: {
        '/legal': ['LegalDocuments', 'legalDocuments'],
        '/legal/new/:type': ['LegalDocumentNew', 'legalDocumentNew'],
    },
    redirects: {},
    urls: {
        legalDocuments: (): string => '/legal',
        legalDocumentNew: (type: 'BAA' | 'DPA'): string => `/legal/new/${type.toLowerCase()}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
