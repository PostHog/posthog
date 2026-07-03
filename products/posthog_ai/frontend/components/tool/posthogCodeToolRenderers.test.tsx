import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { PostHogCodeToolRenderer, POSTHOG_CODE_TOOLS_SERVER } from './posthogCodeToolRenderers'
import { lookupToolRenderer } from './toolRegistry'
import { resolveToolCall } from './toolResolver'

function textBlock(text: string): unknown {
    return { type: 'content', content: { type: 'text', text } }
}

function qualified(tool: string): string {
    return `mcp__${POSTHOG_CODE_TOOLS_SERVER}__${tool}`
}

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: qualified('git_signed_commit'),
        rawServerName: 'posthog',
        rawToolName: '',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('posthog-code tool renderers', () => {
    afterEach(() => cleanup())

    it('renders each signed commit as a GitHub link to its commit URL', () => {
        render(
            <PostHogCodeToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey: qualified('git_signed_commit'),
                    rawInput: { message: 'fix(api): handle null series' },
                    content: [
                        textBlock(
                            'Created 2 signed commit(s) on posthog-code/foo:\n' +
                                '- a1b2c3d https://github.com/posthog/posthog/commit/a1b2c3dabcdef\n' +
                                '- e4f5a6b https://github.com/posthog/posthog/commit/e4f5a6babcdef'
                        ),
                    ],
                })}
            />
        )
        expect(screen.getByText('Signed commits · 2 commits')).toBeInTheDocument()
        expect(screen.getByText('fix(api): handle null series')).toBeInTheDocument()
        // The commit links live in the collapsed accordion, not always-visible — reveal them first.
        expect(screen.queryByRole('link', { name: /a1b2c3d/ })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByRole('link', { name: /a1b2c3d/ })).toHaveAttribute(
            'href',
            'https://github.com/posthog/posthog/commit/a1b2c3dabcdef'
        )
        expect(screen.getByRole('link', { name: /e4f5a6b/ })).toHaveAttribute(
            'href',
            'https://github.com/posthog/posthog/commit/e4f5a6babcdef'
        )
    })

    it.each([
        ['git_signed_commit', { message: 'fix: x', branch: 'b' }, 'fix: x'],
        ['git_signed_merge', { base: 'master', branch: 'feature' }, 'master → feature'],
        ['git_signed_rewrite', { branch: 'feature' }, 'feature'],
    ])('derives the %s subtitle from its inputs', (tool, rawInput, expected) => {
        render(
            <PostHogCodeToolRenderer isLastInGroup message={makeMessage({ resolvedKey: qualified(tool), rawInput })} />
        )
        expect(screen.getByText(expected)).toBeInTheDocument()
    })

    it('falls back to the raw text when a merge reports nothing to do', () => {
        render(
            <PostHogCodeToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey: qualified('git_signed_merge'),
                    rawInput: { base: 'master', branch: 'feature' },
                    content: [textBlock('feature is already up to date with master; nothing to merge.')],
                })}
            />
        )
        expect(screen.getByText('Signed merge')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText(/already up to date/)).toBeInTheDocument()
    })

    it('lists repositories as links to their GitHub pages', () => {
        render(
            <PostHogCodeToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey: qualified('list_repos'),
                    content: [
                        textBlock('posthog/posthog: Product analytics platform\nposthog/posthog-js: JavaScript SDK'),
                    ],
                })}
            />
        )
        expect(screen.getByText('List repositories · 2')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('Product analytics platform')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /posthog-js/ })).toHaveAttribute(
            'href',
            'https://github.com/posthog/posthog-js'
        )
    })

    it('links the cloned repo and shows the target path', () => {
        render(
            <PostHogCodeToolRenderer
                isLastInGroup
                message={makeMessage({
                    resolvedKey: qualified('clone_repo'),
                    rawInput: { repo: 'posthog/posthog', branch: 'main' },
                    content: [
                        textBlock(
                            'Cloned posthog/posthog (posthog) to /home/user/repos/posthog/posthog on branch main.'
                        ),
                    ],
                })}
            />
        )
        expect(screen.getByText('Clone repository')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /posthog\/posthog/ })).toHaveAttribute(
            'href',
            'https://github.com/posthog/posthog'
        )
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText(/\/home\/user\/repos\/posthog\/posthog/)).toBeInTheDocument()
    })

    // The resolver yields the qualified key on the Claude-SDK wire path and the bare key on a native MCP
    // path; the registry must map both so neither adapter falls through to the generic wrench card.
    it.each([
        [
            'claude-sdk',
            {
                rawServerName: 'posthog',
                rawToolName: '',
                input: {},
                meta: { claudeCode: { toolName: qualified('git_signed_commit') } },
            },
            qualified('git_signed_commit'),
        ],
        [
            'native-mcp',
            { rawServerName: POSTHOG_CODE_TOOLS_SERVER, rawToolName: 'git_signed_commit', input: {}, meta: undefined },
            'git_signed_commit',
        ],
    ])('resolves the %s key shape to the signed-commit renderer', (_label, toolCall, expectedKey) => {
        const resolved = resolveToolCall(toolCall)
        expect(resolved.resolvedKey).toEqual(expectedKey)
        expect(lookupToolRenderer(resolved.resolvedKey).displayName).toEqual('Signed commits')
    })
})
