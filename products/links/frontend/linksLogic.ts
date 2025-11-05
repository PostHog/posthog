import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { LinkType } from '~/types'

import type { linksLogicType } from './linksLogicType'

export const linksLogic = kea<linksLogicType>([
    path(() => ['scenes', 'links', 'linksLogic']),
    loaders(() => ({
        links: [
            [] as LinkType[],
            {
                loadLinks: async () => {
                    const response = await api.links.list()
                    return response.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadLinks()
    }),
])
