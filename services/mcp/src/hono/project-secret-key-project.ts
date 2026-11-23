import { ApiClient } from '@/api/client'
import { findPostHogPermissionError, PostHogApiError, PostHogPermissionError } from '@/lib/errors'
import { PROJECT_SECRET_KEY_ACCESS_PATH, PROJECT_SECRET_KEY_REMEDIATION } from '@/lib/project-secret-key'
import type { RequestProperties } from '@/lib/request-properties'
import type { State } from '@/tools/types'

import { getClientIpSigningKeys, getCustomApiBaseUrl } from './constants'

type KeyProjectCache = {
    get: (key: 'projectSecretKeyProjectId') => Promise<State['projectSecretKeyProjectId']>
    set: (key: 'projectSecretKeyProjectId', value: string) => Promise<void>
}

/** The ID of the project a project secret API key belongs to. The key is the only input. */
export async function resolveProjectSecretKeyProjectId(
    props: RequestProperties,
    cache: KeyProjectCache
): Promise<string> {
    const cached = await cache.get('projectSecretKeyProjectId')
    if (cached) {
        return cached
    }
    const baseUrl = getCustomApiBaseUrl()
    if (!baseUrl && process.env.NODE_ENV === 'production') {
        throw new Error('POSTHOG_API_BASE_URL must be set in production.')
    }
    const api = new ApiClient({
        apiToken: props.apiToken,
        baseUrl: baseUrl || 'http://localhost:8010',
        clientUserAgent: props.clientUserAgent,
        clientIp: props.clientIp,
        clientIpSigningKeys: getClientIpSigningKeys(),
    })
    let access: { project_id: number }
    try {
        access = await api.request<{ project_id: number }>({ method: 'GET', path: PROJECT_SECRET_KEY_ACCESS_PATH })
    } catch (error) {
        // 403 covers a key without the scope, a project outside the rollout, and a deleted library.
        const denied = findPostHogPermissionError(error)
        if (denied || (error instanceof PostHogApiError && error.status === 403)) {
            throw new PostHogPermissionError({
                detail: denied?.detail ?? 'The project secret API key cannot read business knowledge.',
                missingScope: denied?.missingScope,
                url: PROJECT_SECRET_KEY_ACCESS_PATH,
                method: 'GET',
                remediation: PROJECT_SECRET_KEY_REMEDIATION,
            })
        }
        throw error
    }
    const projectId = String(access.project_id)
    await cache.set('projectSecretKeyProjectId', projectId)
    return projectId
}
