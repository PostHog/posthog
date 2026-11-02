import { describe, expect, it } from 'vitest'

import { errorTrackingIssueAnalyticsProperties } from '@/tools/errorTracking/analytics'

const ISSUE = '01890c6b-3f1a-7d2e-9b4c-5a6d7e8f9a0b'
const OTHER = '01890c6b-3f1a-7d2e-9b4c-5a6d7e8f9a0c'

describe('errorTrackingIssueAnalyticsProperties', () => {
    it.each([
        ['query-error-tracking-issue', { issueId: ISSUE }],
        ['query-error-tracking-issue-events', { issueId: ISSUE, limit: 5 }],
        ['error-tracking-issues-partial-update', { id: ISSUE, status: 'resolved' }],
        ['error-tracking-issues-assign-partial-update', { id: ISSUE, assignee: null }],
        // Each tool names the issue under its own argument, so a lookup by one key
        // would leave half of these tools unstamped.
        ['error-tracking-issues-merge-create', { id: ISSUE, ids: [] }],
    ])('identifies the issue %s targets', (tool, args) => {
        expect(errorTrackingIssueAnalyticsProperties(tool, args)).toEqual({ error_tracking_issue_id: ISSUE })
    })

    it('records the merged issues apart from the surviving target', () => {
        expect(
            errorTrackingIssueAnalyticsProperties('error-tracking-issues-merge-create', {
                id: ISSUE,
                ids: [OTHER, 'not-an-id'],
            })
        ).toEqual({ error_tracking_issue_id: ISSUE, error_tracking_merged_issue_ids: [OTHER] })
    })

    it.each([
        // Stamping an unrelated tool would put caller text on events it does not describe.
        ['a non-issue tool', 'execute-sql', { id: ISSUE }],
        ['the issues list, which names no single issue', 'query-error-tracking-issues-list', { issueId: ISSUE }],
        ['an unresolved tool name', undefined, { issueId: ISSUE }],
        // The agent's own text, not an ID that could name an issue.
        ['a non-uuid id', 'query-error-tracking-issue', { issueId: "x'; DROP TABLE--" }],
        ['a non-string id', 'error-tracking-issues-partial-update', { id: 42 }],
        ['the wrong argument key', 'query-error-tracking-issue', { id: ISSUE }],
        ['non-object args', 'query-error-tracking-issue', [ISSUE]],
        ['null args', 'query-error-tracking-issue', null],
    ])('records nothing for %s', (_label, tool, args) => {
        expect(errorTrackingIssueAnalyticsProperties(tool, args)).toEqual({})
    })
})
