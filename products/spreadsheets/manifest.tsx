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
        '/spreadsheets': ['Spreadsheets', 'spreadsheets'],
    },
    urls: {
        spreadsheets: (): string => '/spreadsheets',
    },
}
