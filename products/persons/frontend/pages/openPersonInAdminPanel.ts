import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getEuUserId, getUserAdminUrl } from 'lib/utils/userAdmin'

import { ProductKey } from '~/queries/schema/schema-general'
import { PersonType, Region } from '~/types'

export function openInAdminPanelDisabledReason(person: PersonType | null): string | undefined {
    return !person?.properties.email ? 'Person has no email' : undefined
}

export async function openPersonInAdminPanel(person: PersonType | null): Promise<void> {
    try {
        const response = await api.users.list(person?.properties.email)
        const userId = response.results?.[0]?.id
        if (userId) {
            window.open(`/admin/posthog/user/${userId}/change/`, '_blank')
            return
        }

        const euUserId = await getEuUserId(person?.distinct_ids ?? [], { productKey: ProductKey.PERSONS })
        if (euUserId === null) {
            throw new Error('User not found')
        }
        window.open(getUserAdminUrl(Region.EU, euUserId), '_blank')
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        lemonToast.error(`Failed to open admin panel: ${message}`)
    }
}
