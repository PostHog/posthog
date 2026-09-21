import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Groups',
    scenes: {
        Group: {
            name: 'People & groups',
            import: () => import('./frontend/pages/Group'),
            projectBased: true,
        },
        Groups: {
            name: 'Groups',
            import: () => import('./frontend/pages/Groups'),
            projectBased: true,
        },
        GroupsNew: {
            import: () => import('./frontend/pages/GroupsNew'),
            projectBased: true,
        },
    },
    routes: {
        '/groups/:groupTypeIndex': ['Groups', 'groups'],
        '/groups/:groupTypeIndex/new': ['GroupsNew', 'groupsNew'],
        '/groups/:groupTypeIndex/:groupKey': ['Group', 'group'],
        '/groups/:groupTypeIndex/:groupKey/:groupTab': ['Group', 'groupWithTab'],
    },
    urls: {
        groups: (groupTypeIndex: string | number): string => `/groups/${groupTypeIndex}`,
        groupsNew: (groupTypeIndex: string | number): string => `/groups/${groupTypeIndex}/new`,
        // :TRICKY: Note that groupKey is provided by user. We need to override urlPatternOptions for kea-router.
        group: (
            groupTypeIndex: string | number,
            groupKey: string,
            encode: boolean = true,
            tab?: string | null
        ): string =>
            `/groups/${groupTypeIndex}/${encode ? encodeURIComponent(groupKey) : groupKey}${tab ? `/${tab}` : ''}`,
    },
    fileSystemTypes: {
        // TODO: create group node entries in the backend
    },
    treeItemsProducts: [],
}
