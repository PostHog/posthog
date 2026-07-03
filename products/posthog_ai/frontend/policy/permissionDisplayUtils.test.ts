import type { PermissionRequestRecord, ToolInvocation } from '../types/streamTypes'
import { getPostHogExecDisplay, getPermissionDisplay } from './permissionDisplayUtils'

const rawToolCall: ToolInvocation = {
    toolCallId: 'tc-1',
    rawServerName: 'posthog',
    rawToolName: 'exec',
    input: {},
    status: 'pending',
    contentBlocks: [],
}

function makeRequest(overrides: Partial<PermissionRequestRecord> = {}): PermissionRequestRecord {
    return {
        requestId: 'req-1',
        toolCallId: 'tc-1',
        toolName: 'mcp__posthog__exec',
        options: [
            { optionId: 'opt-allow', name: 'Approve', kind: 'allow_once' },
            { optionId: 'opt-reject', name: 'Decline', kind: 'reject' },
        ],
        rawToolCall,
        ...overrides,
    }
}

describe('permissionDisplayUtils', () => {
    it('unwraps PostHog exec call commands into an MCP title and pretty JSON payload', () => {
        const display = getPermissionDisplay(
            makeRequest({
                rawToolCall: {
                    ...rawToolCall,
                    input: { command: 'call execute-sql {"query":"select 1"}' },
                },
            })
        )

        expect(display).toEqual({
            title: 'posthog - execute-sql (MCP)',
            payload: '{\n  "query": "select 1"\n}',
        })
    })

    it('prefers explicit PostHog exec input when present', () => {
        expect(
            getPostHogExecDisplay({
                command: 'call execute-sql {"query":"wrapped"}',
                input: { query: 'explicit' },
            })
        ).toEqual({
            label: 'execute-sql',
            input: '{"query":"explicit"}',
        })
    })

    it('keeps non-JSON PostHog exec args displayable', () => {
        const display = getPermissionDisplay(
            makeRequest({
                rawToolCall: {
                    ...rawToolCall,
                    input: { command: 'search query-' },
                },
            })
        )

        expect(display).toEqual({
            title: 'posthog - Search tools (MCP)',
            payload: 'query-',
        })
    })

    it('formats generic MCP tool input as JSON', () => {
        const display = getPermissionDisplay(
            makeRequest({
                toolName: 'mcp__github__create_issue',
                rawToolCall: {
                    ...rawToolCall,
                    rawServerName: 'github',
                    rawToolName: 'create_issue',
                    input: { owner: 'PostHog', repo: 'posthog' },
                },
            })
        )

        expect(display).toEqual({
            title: 'github - create_issue (MCP)',
            payload: '{\n  "owner": "PostHog",\n  "repo": "posthog"\n}',
        })
    })
})
