import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Referrals',
    scenes: {
        Referrals: {
            name: 'Referrals',
            import: () => import('./frontend/scenes/ReferralsScene'),
            projectBased: true,
            description: 'Share your signup link—attributed signups show up below.',
            iconType: 'link',
        },
    },
    routes: {
        '/referrals': ['Referrals', 'referrals'],
    },
    redirects: {},
    urls: {
        referrals: (): string => '/referrals',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
