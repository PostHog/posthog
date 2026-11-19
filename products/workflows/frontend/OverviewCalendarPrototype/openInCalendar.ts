// PROTOTYPE (throwaway): overview rows open the entry on the calendar page.
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

export function openInCalendar(entryId?: string, variant = 'E'): void {
    router.actions.push(urls.workflows('calendar'), entryId ? { variant, entry: entryId } : { variant })
}
