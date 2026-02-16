import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Streamlit apps',
    urls: {
        streamlitApps: (): string => '/apps',
        streamlitApp: (id: string): string => `/apps/${id}`,
        streamlitAppEdit: (id: string): string => `/apps/${id}/edit`,
        streamlitAppNew: (): string => '/apps/new',
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
        '/apps': ['StreamlitApps', 'streamlitApps'],
        '/apps/new': ['StreamlitAppEdit', 'streamlitAppNew'],
        '/apps/:id': ['StreamlitApp', 'streamlitApp'],
        '/apps/:id/edit': ['StreamlitAppEdit', 'streamlitAppEdit'],
    },
    treeItemsProducts: [
        {
            path: 'Apps',
            intents: [ProductKey.STREAMLIT_APPS],
            href: urls.streamlitApps(),
            type: 'streamlit_app',
            category: 'Tools',
            iconType: 'apps',
            iconColor: ['var(--color-product-data-pipeline-light)'] as FileSystemIconColor,
            sceneKey: 'StreamlitApps',
            sceneKeys: ['StreamlitApps', 'StreamlitApp', 'StreamlitAppEdit'],
        },
    ],
}
