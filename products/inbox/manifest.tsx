import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Self-driving',
    scenes: {},
    routes: {},
    urls: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Self-driving',
            intents: [],
            category: ProductItemCategory.TOOLS,
            iconType: 'inbox' as FileSystemIconType,
            href: urls.selfDriving(),
            flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
            sceneKey: 'SelfDriving',
            sceneKeys: ['SelfDriving'],
        },
    ],
}
