import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Persons',
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
