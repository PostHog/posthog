import { Redirect } from 'expo-router'
import type { ReactElement } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { useDataMode } from '@/demo/demoMode'
import { defaultPageHref, useDefaultPageHydrated, useDefaultPageStore } from '@/features/settings/defaultPageStore'

export default function Index(): ReactElement {
    const mode = useDataMode()
    const status = useAuthStore((state) => state.status)
    const pageHydrated = useDefaultPageHydrated()
    const page = useDefaultPageStore((state) => state.page)
    if (mode === 'loading' || status === 'loading' || !pageHydrated) {
        return <BootSplash />
    }
    return <Redirect href={mode === 'demo' || status === 'signed_in' ? defaultPageHref(page) : '/sign-in'} />
}
