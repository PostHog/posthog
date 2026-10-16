import { Redirect } from 'expo-router'
import type { ReactElement } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { useDataMode } from '@/demo/demoMode'

export default function Index(): ReactElement {
    const mode = useDataMode()
    const status = useAuthStore((state) => state.status)
    if (mode === 'loading' || status === 'loading') {
        return <BootSplash />
    }
    return <Redirect href={mode === 'demo' || status === 'signed_in' ? '/inbox' : '/sign-in'} />
}
