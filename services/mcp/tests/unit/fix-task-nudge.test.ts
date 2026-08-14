import { describe, expect, it } from 'vitest'

import { FIX_TASK_TOOL_NAME, getFixTaskNudge } from '@/lib/fix-task-nudge'

const FLAG_ON = { 'mcp-error-tracking-fix-nudge': true }
const AVAILABLE_TOOLS = [{ name: 'query-error-tracking-issue' }, { name: FIX_TASK_TOOL_NAME }]
const ISSUE_DETAIL = { id: 'issue-1', name: 'TypeError: x is not a function' }

describe('getFixTaskNudge', () => {
    it.each([
        ['query-error-tracking-issue', ISSUE_DETAIL],
        ['query-error-tracking-issue-events', { results: [{ uuid: 'event-1' }] }],
        ['query-error-tracking-issues-list', { results: [ISSUE_DETAIL] }],
    ])('points %s at the fix task tool when every gate passes', (toolName, handlerResult) => {
        const nudge = getFixTaskNudge({
            toolName,
            handlerResult,
            featureFlags: FLAG_ON,
            availableTools: AVAILABLE_TOOLS,
        })
        expect(nudge).toContain(FIX_TASK_TOOL_NAME)
    })

    it.each([
        ['the flag off', { 'mcp-error-tracking-fix-nudge': false }],
        ['flags unevaluated', undefined],
    ])('returns undefined with %s', (_label, featureFlags) => {
        expect(
            getFixTaskNudge({
                toolName: 'query-error-tracking-issue',
                handlerResult: ISSUE_DETAIL,
                featureFlags,
                availableTools: AVAILABLE_TOOLS,
            })
        ).toBeUndefined()
    })

    it('returns undefined when the fix task tool is not callable by this connection', () => {
        expect(
            getFixTaskNudge({
                toolName: 'query-error-tracking-issue',
                handlerResult: ISSUE_DETAIL,
                featureFlags: FLAG_ON,
                availableTools: [{ name: 'query-error-tracking-issue' }],
            })
        ).toBeUndefined()
    })

    it.each([
        ['an empty issue list', 'query-error-tracking-issues-list', { results: [] }],
        ['an empty events page', 'query-error-tracking-issue-events', { results: [] }],
        ['issue detail missing its id', 'query-error-tracking-issue', { name: 'orphan' }],
        ['a string result', 'query-error-tracking-issue', 'plain text'],
    ])('returns undefined for %s', (_label, toolName, handlerResult) => {
        expect(
            getFixTaskNudge({ toolName, handlerResult, featureFlags: FLAG_ON, availableTools: AVAILABLE_TOOLS })
        ).toBeUndefined()
    })

    it('returns undefined for tools outside the error tracking query surface', () => {
        expect(
            getFixTaskNudge({
                toolName: 'query-logs',
                handlerResult: { results: [{ id: 'log-1' }] },
                featureFlags: FLAG_ON,
                availableTools: AVAILABLE_TOOLS,
            })
        ).toBeUndefined()
    })
})
