import { router } from 'kea-router'
import type { MouseEvent } from 'react'

import { newInternalTab } from 'lib/utils/newInternalTab'

/** Row-level navigation for tables whose rows are links: click routes, cmd/ctrl and middle
 *  click open an internal tab, and inner links/buttons keep their own behavior. */
export function rowNavigationProps(url: string): {
    onClick: (e: MouseEvent) => void
    onAuxClick: (e: MouseEvent) => void
} {
    return {
        onClick: (e: MouseEvent) => {
            if ((e.target as HTMLElement).closest('a, button')) {
                return
            }
            if (e.metaKey || e.ctrlKey) {
                e.preventDefault()
                newInternalTab(url)
            } else {
                router.actions.push(url)
            }
        },
        onAuxClick: (e: MouseEvent) => {
            if (e.button === 1 && !(e.target as HTMLElement).closest('a, button')) {
                e.preventDefault()
                newInternalTab(url)
            }
        },
    }
}
