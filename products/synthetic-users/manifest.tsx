import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Synthetic users',
    scenes: {
        SyntheticUsers: {
            import: () => import('./frontend/SyntheticUsersScene'),
            projectBased: true,
            name: 'Synthetic users',
            activityScope: 'SyntheticUsers',
            layout: 'app-container',
            iconType: 'cohort',
            description: 'Create and manage synthetic users for testing.',
        },
    },
    routes: {
        '/synthetic-users': ['SyntheticUsers', 'syntheticUsers'],
    },
    urls: {
        syntheticUsers: (): string => '/synthetic-users',
    },
    fileSystemTypes: {},
    treeItemsProducts: [
        {
            path: 'Synthetic users',
            intents: [ProductKey.SYNTHETIC_USERS],
            category: 'Unreleased',
            iconType: 'persons',
            iconColor: ['var(--color-product-persons-light)'] as FileSystemIconColor,
            href: urls.syntheticUsers(),
            flag: FEATURE_FLAGS.SYNTHETIC_USERS,
            tags: ['alpha'],
            sceneKey: 'SyntheticUsers',
        },
    ],
}
