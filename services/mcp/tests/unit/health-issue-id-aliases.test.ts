import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/health_issues'

// Agents reach health-issues-get from a list result and spell the identifier
// `issue_id` far more often than `id` — production traces show that mismatch as
// the dominant validation failure for the tool. Every alias must normalize to
// `id` (canonical key wins on conflict, then the first-listed alias).
describe('health issue id aliases', () => {
    const ALIAS_KEYS = ['issue_id', 'issueId', 'health_issue_id', 'healthIssueId'] as const
    const UUID = '018f3c2a-7b1e-7000-9c4d-5e6f7a8b9c0d'
    const OTHER_UUID = '018f3c2a-7b1e-7000-9c4d-5e6f7a8b9c0e'
    const schema = GENERATED_TOOLS['health-issues-get']!().schema

    it.each([
        ['id', { id: UUID }, UUID],
        ['issue_id', { issue_id: UUID }, UUID],
        ['issueId', { issueId: UUID }, UUID],
        ['health_issue_id', { health_issue_id: UUID }, UUID],
        ['healthIssueId', { healthIssueId: UUID }, UUID],
        ['id over aliases on conflict', { id: UUID, issue_id: OTHER_UUID }, UUID],
        ['first-listed alias on alias conflict', { issue_id: UUID, issueId: OTHER_UUID }, UUID],
    ])('accepts %s', (_label, input, expected) => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        const data = result.data as Record<string, unknown>
        expect(data.id).toEqual(expected)
        for (const alias of ALIAS_KEYS) {
            expect(data).not.toHaveProperty(alias)
        }
    })

    it('still rejects a call with no identifier', () => {
        expect(schema.safeParse({}).success).toBe(false)
    })
})
