import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Spreadsheets',
    scenes: {
        Spreadsheets: {
            name: 'Spreadsheets',
            import: () => import('./frontend/scene'),
            projectBased: true,
            layout: 'app-raw-no-header',
            hideProjectNotice: true,
        },
    },
    routes: {
        '/spreadsheets/:id': ['Spreadsheets', 'spreadsheets'],
    },
    urls: {
        spreadsheets: (shortId?: string): string => {
            if (shortId) {
                return `/spreadsheets/${shortId}`
            }

            return '/spreadsheets/new'
        },
    },
}
