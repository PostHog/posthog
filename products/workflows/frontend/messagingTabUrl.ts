import { urls } from 'scenes/urls'

import type { MessagingNavTabKey } from './messagingTabs'

/** The URL of a Messaging tab in the section (workflows, broadcasts or transactional) that `pathname` is in. */
export function messagingTabUrl(pathname: string, tab: MessagingNavTabKey): string {
    if (pathname.includes('/broadcasts')) {
        return urls.broadcasts(tab)
    }
    if (pathname.includes('/transactional')) {
        return urls.transactional(tab)
    }
    return urls.workflows(tab)
}
