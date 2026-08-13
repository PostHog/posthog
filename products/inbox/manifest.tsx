import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Inbox',
    scenes: {},
    routes: {},
    urls: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Inbox',
            intents: [],
            category: ProductItemCategory.TOOLS,
            iconType: 'inbox' as FileSystemIconType,
            href: urls.inbox(),
            flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
            sceneKey: 'Inbox',
            sceneKeys: ['Inbox'],
        },
    ],
}
