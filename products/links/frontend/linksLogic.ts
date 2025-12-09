import { actions, afterMount, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { LinkType } from '~/types'

import type { linksLogicType } from './linksLogicType'

export const linksLogic = kea<linksLogicType>([
    path(() => ['scenes', 'links', 'linksLogic']),
    actions({
        deleteLink: (linkId: LinkType['id']) => ({ linkId }),
    }),
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
    listeners(({ actions, values }) => ({
        deleteLink: async ({ linkId }) => {
            try {
                await api.links.delete(linkId)
                lemonToast.info('Link deleted. Existing `$link_clicked` events will be kept for future analysis')
                actions.loadLinksSuccess(values.links.filter((link) => link.id !== linkId))
                deleteFromTree('link', linkId)
            } catch (e) {
                lemonToast.error(`Error deleting Link: ${e}`)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLinks()
    }),
])
