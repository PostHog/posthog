import { ProductManifest } from '../../frontend/src/types'

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
}
