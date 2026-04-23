import { describe, expect, it } from 'vitest'

import {
    CODING_AGENT_CLIENT_NAME_FRAGMENTS,
    POSTHOG_CODE_CONSUMER,
    isCodingAgentClient,
    isPostHogCodeConsumer,
} from '@/lib/client-detection'

describe('isCodingAgentClient', () => {
    describe('detects known coding-agent clients', () => {
        it.each([
            // Exact names from the fragment list.
            ['claude-code'],
            ['cline'],
            ['roo-code'],
            ['roo-cline'],
            ['continue'],
            ['codex'],
            ['windsurf'],
            ['zed'],
            ['aider'],
            ['copilot'],
        ])('returns true for %s', (clientName) => {
            expect(isCodingAgentClient(clientName)).toBe(true)
        })

        it.each([
            // Realistic variants MCP servers actually see.
            ['Claude Code'],
            ['CLAUDE-CODE'],
            ['claude-code-cli'],
            ['claude-code/1.2.3'],
            ['cline-bot'],
            ['roo-code-editor'],
            ['Continue'],
            ['github.copilot'],
            ['GitHub Copilot Chat'],
            ['zed-editor'],
            ['Codex CLI'],
        ])('returns true for variant %s (case-insensitive substring match)', (clientName) => {
            expect(isCodingAgentClient(clientName)).toBe(true)
        })
    })

    describe('does not match non-coding clients', () => {
        it.each([
            ['Claude Desktop'],
            ['claude-desktop'],
            ['mcp-inspector'],
            ['Slack'],
            ['some-random-tool'],
            ['PostHog'],
            [''],
        ])('returns false for %s', (clientName) => {
            expect(isCodingAgentClient(clientName)).toBe(false)
        })
    })

    describe('explicitly excluded clients', () => {
        // Cursor sends content[].text to the model and displays structuredContent in UI,
        // so the workaround isn't needed. Guard against someone adding it back.
        it('returns false for cursor (intentionally excluded)', () => {
            expect(isCodingAgentClient('cursor')).toBe(false)
            expect(isCodingAgentClient('Cursor')).toBe(false)
            expect(isCodingAgentClient('cursor-editor')).toBe(false)
        })
    })

    describe('edge cases', () => {
        it('returns false for undefined', () => {
            expect(isCodingAgentClient(undefined)).toBe(false)
        })

        it('returns false for empty string', () => {
            expect(isCodingAgentClient('')).toBe(false)
        })

        it('treats whitespace-only as non-match', () => {
            expect(isCodingAgentClient('   ')).toBe(false)
        })
    })

    it('keeps the fragment list non-empty and lowercased', () => {
        expect(CODING_AGENT_CLIENT_NAME_FRAGMENTS.length).toBeGreaterThan(0)
        for (const fragment of CODING_AGENT_CLIENT_NAME_FRAGMENTS) {
            expect(fragment).toBe(fragment.toLowerCase())
            expect(fragment.length).toBeGreaterThan(0)
        }
    })
})

describe('isPostHogCodeConsumer', () => {
    it('matches the exact PostHog Code consumer value', () => {
        expect(isPostHogCodeConsumer(POSTHOG_CODE_CONSUMER)).toBe(true)
        expect(isPostHogCodeConsumer('posthog-code')).toBe(true)
    })

    it.each([['posthog_code'], ['PostHog-Code'], ['posthog-code-v2'], ['posthog'], ['slack'], ['']])(
        'returns false for %s (must be exact match)',
        (consumer) => {
            expect(isPostHogCodeConsumer(consumer)).toBe(false)
        }
    )

    it('returns false for undefined', () => {
        expect(isPostHogCodeConsumer(undefined)).toBe(false)
    })
})
