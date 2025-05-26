import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Groups',
    urls: {
        groups: (groupTypeIndex: string | number): string => `/groups/${groupTypeIndex}`,
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
    treeItemsProducts: [
        {
            path: 'Group analytics',
            iconType: 'cohort',
            href: urls.groups(0),
            visualOrder: PRODUCT_VISUAL_ORDER.groups,
        },
    ],
}
