import { vi, type Mock } from 'vitest'

import type { ApiClient } from '@/api/client'

export interface SelfDrivingResponses {
    status?: () => unknown
    onboarding?: () => unknown
}

type RequestOptions = Parameters<ApiClient['request']>[0]

/** Answers the inbox status and onboarding reads by request path, so a test can set or fail each one on its own. */
export function stubSelfDrivingRequests({
    status = () => ({ setup_state: 'not_started' }),
    onboarding = () => ({ completed_at: null, draft: null, github_optional_available: false }),
}: SelfDrivingResponses = {}): Mock<(options: RequestOptions) => Promise<unknown>> {
    return vi.fn(async ({ path }: RequestOptions) => {
        if (path.endsWith('/signals/inbox_status/')) {
            return status()
        }
        if (path.endsWith('/signals/onboarding/')) {
            return onboarding()
        }
        throw new Error(`Unexpected request to ${path}`)
    })
}

export function inboxStatusReads(request: unknown): number {
    return vi
        .mocked(request as Mock<(options: RequestOptions) => Promise<unknown>>)
        .mock.calls.filter(([{ path }]) => path.endsWith('/signals/inbox_status/')).length
}
