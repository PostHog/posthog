import { objectKindLink } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import type { AttachedContextItem } from '../types/contextTypes'

function pathOnly(url: string): string {
    return url.split(/[?#]/)[0].replace(/\/+$/, '')
}

/** The app page a context item points at, without a project prefix. Null when the item has no page of its own. */
export function contextItemPath(item: AttachedContextItem): string | null {
    if (item.key === undefined || item.key === '') {
        return null
    }
    return objectKindLink(item.type, String(item.key), '').url
}

/** Whether the browser already shows that page, so a click on the chip must not navigate. */
export function isOnContextItemPage(path: string, pathname: string): boolean {
    return pathOnly(removeProjectIdIfPresent(pathname)) === pathOnly(path)
}
