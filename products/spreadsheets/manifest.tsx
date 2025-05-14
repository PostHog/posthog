import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Spreadsheets',
    scenes: {
        Spreadsheets: {
            name: 'Spreadsheets',
            import: () => import('./frontend/scene'),
            projectBased: true,
        },
    },
    routes: {
        '/spreadsheets': ['Spreadsheets', 'spreadsheets'],
    },
    urls: {
        spreadsheets: (): string => '/spreadsheets',
    },
}
