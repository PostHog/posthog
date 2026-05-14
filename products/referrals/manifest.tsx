import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Referrals',
    scenes: {
        Referrals: {
            name: 'Referrals',
            import: () => import('./frontend/scenes/ReferralsScene'),
            projectBased: true,
            description:
                'Drop your referral link wherever you talk up PostHog. Signups that land through it show up below, with timing, who joined, and whether they have shipped data yet.',
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
