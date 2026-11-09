import { objectKindLink } from 'lib/components/AgentObjectTags/rewriteAgentObjectTags'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import type { AttachedContextItem } from '~/layout/ai/attachedContext'

const OBJECT_KIND_BY_CONTEXT_TYPE: Record<string, string> = {
    error_tracking_issue: 'error',
    signal_report: 'report',
}

function pathOnly(url: string): string {
    return url.split(/[?#]/)[0].replace(/\/+$/, '')
}

export function contextItemPath(item: Pick<AttachedContextItem, 'type' | 'key' | 'pageId'>): string | null {
    const pageId = item.pageId === undefined ? item.key : item.pageId
    if (pageId === undefined || pageId === null || pageId === '') {
        return null
    }
    if (item.type === 'notebook') {
        return urls.notebook(String(pageId))
    }
    return objectKindLink(OBJECT_KIND_BY_CONTEXT_TYPE[item.type] ?? item.type, String(pageId), '').url
}

/**
 * Whether the browser already shows that page, so a click on the chip must not navigate. A sub-route such as
 * `/insights/:id/edit` shows the same resource, and a click would leave the mode the user is in.
 */
export function isOnContextItemPage(path: string, pathname: string): boolean {
    const current = pathOnly(removeProjectIdIfPresent(pathname))
    const target = pathOnly(path)
    return current === target || current.startsWith(`${target}/`)
}
