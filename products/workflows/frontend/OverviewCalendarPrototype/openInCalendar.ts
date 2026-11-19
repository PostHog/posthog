// PROTOTYPE (throwaway): the overview links into the shipped send calendar. In the build an entry opens its
// broadcast or workflow; the invented entries here have no page, so a toast stands in.
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function openInCalendar(entryId?: string): void {
    if (entryId) {
        lemonToast.info('In the build, this opens the broadcast or workflow.')
        return
    }
    router.actions.push(urls.workflows('calendar'))
}
