import { useMemo } from 'react'

import type { ProjectScope } from '@/api/reports'

import { useAuthStore } from './authStore'

export function useProjectScope(): ProjectScope | null {
    const signedIn = useAuthStore((state) => state.signedIn)
    const host = useAuthStore((state) => state.host)
    const projectId = useAuthStore((state) => state.projectId)
    return useMemo(
        () => (signedIn && host && projectId !== null ? { host: host.replace(/\/$/, ''), projectId } : null),
        [signedIn, host, projectId]
    )
}
