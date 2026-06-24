import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Growth',
    scenes: {
        IdentityMatching: {
            name: 'Identity matching',
            import: () => import('./frontend/IdentityMatchingScene'),
            projectBased: true,
            activityScope: 'IdentityMatching',
            description:
                'Review probable links between anonymous visitors and identified persons, recovered from first-party signals.',
            iconType: 'persons',
        },
    },
    routes: {
        '/identity-matching': ['IdentityMatching', 'identityMatching'],
    },
    urls: {
        identityMatching: (): string => '/identity-matching',
    },
    treeItemsProducts: [
        {
            path: 'Identity matching',
            intents: [ProductKey.MARKETING_ANALYTICS],
            category: ProductItemCategory.UNRELEASED,
            href: urls.identityMatching(),
            flag: FEATURE_FLAGS.IDENTITY_MATCHING,
            tags: ['alpha'],
            iconType: 'persons',
            sceneKey: 'IdentityMatching',
        },
    ],
}
