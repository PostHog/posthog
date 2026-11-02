import { Redirect } from 'expo-router'
import { type ReactElement, useEffect, useRef } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { useDataMode } from '@/demo/demoMode'
import {
    defaultPageHref,
    resolveStartPage,
    sessionOrgAiStatus,
    settleDefaultPage,
    useDefaultPageHydrated,
    useDefaultPageStore,
} from '@/features/settings/defaultPageStore'

export default function Index(): ReactElement {
    const mode = useDataMode()
    const status = useAuthStore((state) => state.status)
    const orgStatus = useAuthStore((state) => (mode === 'live' ? sessionOrgAiStatus(state) : null))
    const pageHydrated = useDefaultPageHydrated()
    const page = useDefaultPageStore((state) => state.page)
    const ready = mode !== 'loading' && status !== 'loading' && pageHydrated
    const settles = ready && mode === 'live' && status === 'signed_in'
    const settled = useRef(false)

    useEffect(() => {
        if (settles && !settled.current) {
            settled.current = true
            settleDefaultPage()
        }
    }, [settles])

    if (!ready) {
        return <BootSplash />
    }
    if (mode !== 'demo' && status !== 'signed_in') {
        return <Redirect href="/sign-in" />
    }
    return <Redirect href={defaultPageHref(resolveStartPage(page, orgStatus).page)} />
}
