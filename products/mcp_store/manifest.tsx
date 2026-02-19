import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'MCP servers',
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'MCP servers',
            category: 'Tools',
            intents: [ProductKey.MCP_STORE],
            href: urls.settings('mcp-servers'),
            flag: FEATURE_FLAGS.MCP_SERVERS,
        },
    ],
}
