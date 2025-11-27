import { PersonsTabType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Persons',
    urls: {
        personByDistinctId: (id: string, encode: boolean = true, activeTab?: PersonsTabType): string => {
            const path = encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`
            return activeTab ? `${path}#activeTab=${activeTab}` : path
        },
        personByUUID: (uuid: string, encode: boolean = true, activeTab?: PersonsTabType): string => {
            const path = encode ? `/persons/${encodeURIComponent(uuid)}` : `/persons/${uuid}`
            return activeTab ? `${path}#activeTab=${activeTab}` : path
        },
        persons: (): string => '/persons',
    },
    fileSystemTypes: {},
    treeItemsProducts: [],
}
