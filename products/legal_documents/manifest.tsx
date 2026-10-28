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
        // The settings navigation's home for the list, next to billing. The /legal routes stay until links move over.
        '/organization/legal': ['LegalDocuments', 'organizationLegalDocuments'],
    },
    redirects: {},
    urls: {
        legalDocuments: (): string => '/legal',
        legalDocumentNew: (type: 'BAA' | 'DPA'): string => `/legal/new/${type.toLowerCase()}`,
        organizationLegalDocuments: (): string => '/organization/legal',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
