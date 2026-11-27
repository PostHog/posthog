import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockIsFeatureEnabled, flagsRequests, batches, flagsResponse } = vi.hoisted(() => ({
    mockIsFeatureEnabled: vi.fn(),
    flagsRequests: [] as Record<string, unknown>[],
    batches: [] as { batch: { event: string; distinct_id: string; properties: Record<string, unknown> }[] }[],
    flagsResponse: { current: {} as Record<string, unknown> },
}))
// Mock the client `flags.ts` consumes, not posthog-node directly: `getPostHogClient()`
// returns a `PostHogMCP` (a posthog-node subclass) from the externalized
// `@posthog/mcp-analytics`, whose internal posthog-node import a `vi.mock('posthog-node')`
// here would not intercept.
vi.mock('@/lib/posthog/client', async () => {
    const { PostHogMCP } = await import('@posthog/mcp-analytics')
    const client = new PostHogMCP('phc_test', {
        host: 'https://flags.posthog.invalid',
        flushAt: 1,
        flushInterval: 0,
        disableCompression: true,
        fetch: async (url, options) => {
            const body = JSON.parse(String(options.body))
            if (url.includes('/flags/')) {
                flagsRequests.push(body)
                return { status: 200, text: async () => '', json: async () => flagsResponse.current }
            }
            batches.push(body)
            return { status: 200, text: async () => '{"results":{}}', json: async () => ({ results: {} }) }
        },
    })
    client.isFeatureEnabled = mockIsFeatureEnabled
    return { getPostHogClient: () => client }
})

// Must import after vi.mock
import { getPostHogClient } from '@/lib/posthog/client'
import { evaluateFeatureFlags, isFeatureFlagEnabled } from '@/lib/posthog/flags'

describe('isFeatureFlagEnabled', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('should return true when the flag is enabled', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(true)
        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('mcp-version-2', 'user-123', undefined)
    })

    it('should return false when the flag is disabled', async () => {
        mockIsFeatureEnabled.mockResolvedValue(false)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(false)
    })

    it('should return false when the flag returns undefined', async () => {
        mockIsFeatureEnabled.mockResolvedValue(undefined)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(false)
    })

    it('should return false when the client throws', async () => {
        mockIsFeatureEnabled.mockRejectedValue(new Error('network error'))

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(false)
    })

    it('should forward groups as options when provided', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        await isFeatureFlagEnabled('notebooks-collaboration', 'user-123', { organization: 'org-abc' })

        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('notebooks-collaboration', 'user-123', {
            groups: { organization: 'org-abc' },
        })
    })

    it('should omit the options arg when groups is an empty object', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        await isFeatureFlagEnabled('flag-x', 'user-123', {})

        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('flag-x', 'user-123', undefined)
    })
})

describe('evaluateFeatureFlags', () => {
    const flag = (key: string, enabled: boolean, variant?: string, payload?: unknown): Record<string, unknown> => ({
        key,
        enabled,
        variant,
        reason: { code: enabled ? 'condition_match' : 'no_condition_match' },
        metadata: { id: 1, version: 1, payload: payload === undefined ? undefined : JSON.stringify(payload) },
    })

    const flagCalledEvents = async (): Promise<
        { event: string; distinct_id: string; properties: Record<string, unknown> }[]
    > => {
        await getPostHogClient().flush()
        return batches.flatMap(({ batch }) => batch).filter(({ event }) => event === '$feature_flag_called')
    }

    beforeEach(() => {
        flagsRequests.length = 0
        batches.length = 0
        flagsResponse.current = {
            flags: {
                'flag-on': flag('flag-on', true, undefined, { message: 'Example invitation' }),
                'flag-off': flag('flag-off', false, undefined, { message: 'Off' }),
                'flag-legacy': flag('flag-legacy', true, '', { message: 'Legacy variant' }),
                'flag-without-payload': {
                    ...flag('flag-without-payload', true),
                    metadata: { id: 3, version: 1, payload: null },
                },
                'flag-empty-payload': {
                    ...flag('flag-empty-payload', true),
                    metadata: { id: 4, version: 1, payload: '' },
                },
                'xpm-mcp-placement': flag('xpm-mcp-placement', true, 'after_cohorts_create', {
                    label: 'Email the people in this cohort',
                }),
            },
            errorsWhileComputingFlags: false,
            requestId: 'request-1',
        }
    })

    it('returns the values and payloads of the requested flags without reporting an exposure', async () => {
        const result = await evaluateFeatureFlags(
            ['flag-on', 'flag-off', 'flag-legacy', 'flag-without-payload', 'flag-empty-payload', 'xpm-mcp-placement'],
            'user-123',
            { organization: 'org-abc' }
        )

        expect({ flags: result.flags, payloads: result.payloads }).toEqual({
            flags: {
                'flag-on': true,
                'flag-off': false,
                'flag-legacy': '',
                'flag-without-payload': true,
                'flag-empty-payload': true,
                'xpm-mcp-placement': 'after_cohorts_create',
            },
            payloads: {
                'flag-on': { message: 'Example invitation' },
                'flag-legacy': { message: 'Legacy variant' },
                'xpm-mcp-placement': { label: 'Email the people in this cohort' },
            },
        })
        expect(flagsRequests).toMatchObject([
            {
                distinct_id: 'user-123',
                groups: { organization: 'org-abc' },
                flag_keys_to_evaluate: [
                    'flag-on',
                    'flag-off',
                    'flag-legacy',
                    'flag-without-payload',
                    'flag-empty-payload',
                    'xpm-mcp-placement',
                ],
            },
        ])
        expect(await flagCalledEvents()).toEqual([])
    })

    it('reports the exposure of one flag with the variant and groups it was evaluated with', async () => {
        const evaluation = await evaluateFeatureFlags(['flag-on', 'xpm-mcp-placement'], 'user-123', {
            organization: 'org-abc',
        })

        evaluation.reportExposure?.('xpm-mcp-placement')

        expect(await flagCalledEvents()).toMatchObject([
            {
                distinct_id: 'user-123',
                properties: {
                    $feature_flag: 'xpm-mcp-placement',
                    $feature_flag_response: 'after_cohorts_create',
                    $groups: { organization: 'org-abc' },
                },
            },
        ])
    })

    it('sends no groups when none are given', async () => {
        await evaluateFeatureFlags(['flag-on'], 'user-123')

        expect(flagsRequests).toHaveLength(1)
        expect(flagsRequests[0]?.groups).toEqual({})
    })

    it('makes no request and reports no exposure when no flag keys are requested', async () => {
        const evaluation = await evaluateFeatureFlags([], 'user-123', { organization: 'org-abc' })

        evaluation.reportExposure?.('xpm-mcp-placement')

        expect(evaluation).toMatchObject({ flags: {}, payloads: {} })
        expect(flagsRequests).toEqual([])
        expect(await flagCalledEvents()).toEqual([])
    })
})
