import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Persons',
    scenes: {
        Person: {
            projectBased: true,
            name: 'People',
            import: () => import('./frontend/pages/PersonScene'),
            activityScope: ActivityScope.PERSON,
            iconType: 'user',
        },
        Persons: {
            projectBased: true,
            name: 'Persons',
            description: 'A catalog of all the people behind your events',
            import: () => import('./frontend/pages/PersonsScene'),
            activityScope: ActivityScope.PERSON,
            iconType: 'persons',
        },
    },
    routes: {
        '/person/*': ['Person', 'personByDistinctId'],
        '/persons/*': ['Person', 'personByUUID'],
        '/persons': ['Persons', 'persons'],
    },
    urls: {
        personByDistinctId: (id: string, encode: boolean = true): string =>
            encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`,
        personByUUID: (uuid: string, encode: boolean = true): string =>
            encode ? `/persons/${encodeURIComponent(uuid)}` : `/persons/${uuid}`,
        persons: (): string => '/persons',
    },
    fileSystemTypes: {},
    treeItemsProducts: [],
}
