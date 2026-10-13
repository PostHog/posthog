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
            displayLabel: 'Self-driving inbox',
            intents: [],
            category: ProductItemCategory.TOOLS,
            iconType: 'inbox' as FileSystemIconType,
            href: urls.inbox(),
            searchKeywords: ['signals', 'triage', 'findings'],
            searchTabs: [
                { name: 'Reports', href: urls.inbox('reports') },
                { name: 'Scouts', href: urls.inbox('scouts') },
            ],
            flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
            tags: ['beta'],
            sceneKey: 'Inbox',
            sceneKeys: ['Inbox'],
        },
    ],
}
