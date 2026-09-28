import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { findCreatedBroadcastId } from './newBroadcastHandoff'

const BROADCAST_ID = '2f1e9c3a-5b7d-4e8f-9a0b-1c2d3e4f5a6b'
const NAME = 'Spring sale'

describe('findCreatedBroadcastId', () => {
    let requestedTypes: string | null

    beforeEach(() => {
        requestedTypes = null
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': ({ request }) => {
                    requestedTypes = new URL(request.url).searchParams.get('type')
                    return [
                        200,
                        {
                            results: [
                                { id: 'older', name: NAME, created_at: '2026-09-01T00:00:00Z' },
                                { id: BROADCAST_ID, name: NAME, created_at: '2026-09-15T00:00:00Z' },
                                { id: 'other', name: `${NAME} v2`, created_at: '2026-09-16T00:00:00Z' },
                            ],
                            count: 3,
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    // A workflow can share the name, so the lookup must only consider broadcasts.
    it.each([
        { name: 'the newest exact match among broadcasts', input: NAME, expected: BROADCAST_ID, types: 'broadcast' },
        { name: 'null for a blank name', input: '  ', expected: null, types: null },
    ])('returns $name', async ({ input, expected, types }) => {
        await expect(findCreatedBroadcastId(input)).resolves.toBe(expected)
        expect(requestedTypes).toBe(types)
    })
})
