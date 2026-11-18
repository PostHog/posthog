import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Releases',
    scenes: {
        ReleaseCalendar: {
            name: 'Release calendar',
            import: () => import('./frontend/ReleaseCalendar'),
            projectBased: true,
            description: 'One row for each release, with its flags, experiments and early access.',
        },
        Releases: {
            name: 'Releases',
            import: () => import('./frontend/ReleaseList'),
            projectBased: true,
        },
        ReleaseAll: {
            name: 'View all',
            import: () => import('./frontend/ReleaseAll'),
            projectBased: true,
        },
        Release: {
            name: 'Release',
            import: () => import('./frontend/Release'),
            projectBased: true,
        },
    },
    routes: {
        '/releases': ['ReleaseAll', 'releases'],
        '/releases/calendar': ['ReleaseCalendar', 'releaseCalendar'],
        '/releases/list': ['Releases', 'releaseList'],
        '/releases/:id': ['Release', 'release'],
    },
    redirects: {},
    urls: {
        releases: (): string => '/releases',
        releaseCalendar: (): string => '/releases/calendar',
        releaseList: (): string => '/releases/list',
        release: (id: string): string => `/releases/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
