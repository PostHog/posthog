import { Redirect } from 'expo-router'
import type { ReactElement } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { useDataMode } from '@/demo/demoMode'
import {
    defaultPageHref,
    effectiveDefaultPage,
    useDefaultPageHydrated,
    useDefaultPageStore,
} from '@/features/settings/defaultPageStore'

export default function Index(): ReactElement {
    const mode = useDataMode()
    const status = useAuthStore((state) => state.status)
    const pageHydrated = useDefaultPageHydrated()
    const page = useDefaultPageStore((state) => state.page)
    const ready = mode !== 'loading' && status !== 'loading' && pageHydrated

    if (!ready) {
        return <BootSplash />
    }
    if (mode !== 'demo' && status !== 'signed_in') {
        return <Redirect href="/sign-in" />
    }
    return <Redirect href={defaultPageHref(effectiveDefaultPage(page))} />
}
