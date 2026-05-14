import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Semantic layer',
    scenes: {
        SemanticLayerProposals: {
            name: 'Proposals',
            import: () => import('./frontend/SemanticLayerProposalsScene'),
            projectBased: true,
            description:
                'Review AI-generated proposals for your semantic layer — new definitions, drift alerts, duplicates, schema sync, relationships, and metadata improvements.',
            iconType: 'data_warehouse',
        },
    },
    routes: {
        '/semantic-layer/proposals': ['SemanticLayerProposals', 'semanticLayerProposals'],
        '/semantic-layer/proposals/:id': ['SemanticLayerProposals', 'semanticLayerProposal'],
    },
    urls: {
        semanticLayerProposals: (): string => '/semantic-layer/proposals',
        semanticLayerProposal: (id: string): string => `/semantic-layer/proposals/${id}`,
    },
}
