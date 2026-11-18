import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { findCreatedTemplateId } from './newTemplateHandoff'

const TEMPLATE_ID = '2f1e9c3a-5b7d-4e8f-9a0b-1c2d3e4f5a6b'
const OLDER_ID = '7a1b2c3d-0000-4e8f-9a0b-1c2d3e4f5a6b'
const NAME = 'Welcome email'

describe('findCreatedTemplateId', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': {
                    results: [
                        { id: 'other', name: `${NAME} v2`, created_at: '2026-09-16T00:00:00Z' },
                        { id: TEMPLATE_ID, name: NAME, created_at: '2026-09-15T00:00:00Z' },
                        { id: OLDER_ID, name: NAME, created_at: '2026-09-01T00:00:00Z' },
                    ],
                    count: 3,
                },
            },
        })
        initKeaTests()
    })

    // The list has no search, so only the exact name counts, and the newest of those is the template just made.
    it.each([
        { name: 'the newest exact match', input: NAME, expected: TEMPLATE_ID },
        { name: 'null for a blank name', input: '  ', expected: null },
        { name: 'null for a non-string name', input: 42, expected: null },
    ])('returns $name', async ({ input, expected }) => {
        await expect(findCreatedTemplateId(input)).resolves.toBe(expected)
    })
})
