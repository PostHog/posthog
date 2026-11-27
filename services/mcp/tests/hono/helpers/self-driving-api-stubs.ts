import { vi, type Mock } from 'vitest'

import type { ApiClient } from '@/api/client'

export interface SelfDrivingResponses {
    status?: () => unknown
}

type RequestOptions = Parameters<ApiClient['request']>[0]

/** Answers the inbox status read and rejects every other path, so a test fails when the guidance requests anything else. */
export function stubSelfDrivingRequests({
    status = () => ({ setup_state: 'not_started' }),
}: SelfDrivingResponses = {}): Mock<(options: RequestOptions) => Promise<unknown>> {
    return vi.fn(async ({ path }: RequestOptions) => {
        if (path.endsWith('/signals/inbox_status/')) {
            return status()
        }
        throw new Error(`Unexpected request to ${path}`)
    })
}

export function inboxStatusReads(request: unknown): number {
    return vi
        .mocked(request as Mock<(options: RequestOptions) => Promise<unknown>>)
        .mock.calls.filter(([{ path }]) => path.endsWith('/signals/inbox_status/')).length
}
