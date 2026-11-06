import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { findCreatedWorkflowId } from './newWorkflowHandoff'

const WORKFLOW_ID = '2f1e9c3a-5b7d-4e8f-9a0b-1c2d3e4f5a6b'
const OLDER_ID = '7a1b2c3d-0000-4e8f-9a0b-1c2d3e4f5a6b'
const NAME = 'Win back inactive users'

describe('findCreatedWorkflowId', () => {
    beforeEach(() => {
        useMocks({
            get: {
                // Ordered by update time like the real list, so the same-named older draft comes first.
                '/api/environments/:team_id/hog_flows/': {
                    results: [
                        { id: OLDER_ID, name: NAME, created_at: '2026-09-01T00:00:00Z' },
                        { id: WORKFLOW_ID, name: NAME, created_at: '2026-09-15T00:00:00Z' },
                        { id: 'other', name: `${NAME} v2`, created_at: '2026-09-16T00:00:00Z' },
                    ],
                    count: 3,
                },
            },
        })
        initKeaTests()
    })

    // The list is a substring search, so only the exact name counts, and the newest of those is the draft just made.
    it.each([
        { name: 'the newest exact match', input: NAME, expected: WORKFLOW_ID },
        { name: 'null for a blank name', input: '  ', expected: null },
        { name: 'null for a non-string name', input: 42, expected: null },
    ])('returns $name', async ({ input, expected }) => {
        await expect(findCreatedWorkflowId(input)).resolves.toBe(expected)
    })
})
