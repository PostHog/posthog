import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FEATURE_FLAGS } from '../../frontend/src/lib/constants'
import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Streamlit apps',
    urls: {
        streamlitApps: (): string => '/streamlit-apps',
        streamlitApp: (id: string): string => `/streamlit-apps/${id}`,
        streamlitAppEdit: (id: string): string => `/streamlit-apps/${id}/edit`,
        streamlitAppNew: (): string => '/streamlit-apps/new',
    },
    scenes: {
        StreamlitApps: {
            name: 'Streamlit apps',
            import: () => import('./frontend/StreamlitApps'),
            projectBased: true,
        },
        StreamlitApp: {
            name: 'Streamlit app',
            import: () => import('./frontend/StreamlitApp'),
            projectBased: true,
        },
        StreamlitAppEdit: {
            name: 'Edit Streamlit app',
            import: () => import('./frontend/StreamlitAppEdit'),
            projectBased: true,
        },
    },
    routes: {
        '/streamlit-apps': ['StreamlitApps', 'streamlitApps'],
        '/streamlit-apps/new': ['StreamlitAppEdit', 'streamlitAppNew'],
        '/streamlit-apps/:id': ['StreamlitApp', 'streamlitApp'],
        '/streamlit-apps/:id/edit': ['StreamlitAppEdit', 'streamlitAppEdit'],
    },
    treeItemsProducts: [
        {
            path: 'Apps',
            intents: [ProductKey.STREAMLIT_APPS],
            href: urls.streamlitApps(),
            type: 'streamlit_app',
            category: ProductItemCategory.UNRELEASED,
            flag: FEATURE_FLAGS.STREAMLIT_APPS,
            iconType: 'tools',
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
            sceneKey: 'StreamlitApps',
            sceneKeys: ['StreamlitApps', 'StreamlitApp', 'StreamlitAppEdit'],
        },
    ],
}
