import { describe, expect, it } from 'vitest'

import {
    CODING_AGENT_CLIENT_NAME_FRAGMENTS,
    DEFAULT_CLIENT_CAPABILITIES,
    MCPClientProfile,
    POSTHOG_CODE_CONSUMER,
    VIBE_CODING_OAUTH_CLIENT_NAME_FRAGMENTS,
    isCodingAgentClient,
    isPostHogCodeConsumer,
    isVibeCodingClient,
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

describe('isVibeCodingClient', () => {
    it.each([
        ['Lovable'],
        ['lovable'],
        ['LOVABLE'],
        ['Lovable.dev'],
        ['lovable-app'],
        ['Replit'],
        ['replit'],
        ['Replit Agent'],
        ['replit-ai'],
    ])('returns true for OAuth client name %s', (oauthClientName) => {
        expect(isVibeCodingClient(oauthClientName)).toBe(true)
    })

    it.each([['Claude Code (posthog)'], ['Cursor'], ['some-random-app'], ['']])(
        'returns false for OAuth client name %s',
        (oauthClientName) => {
            expect(isVibeCodingClient(oauthClientName)).toBe(false)
        }
    )

    it('returns false for undefined', () => {
        expect(isVibeCodingClient(undefined)).toBe(false)
    })

    it('keeps the fragment list non-empty and lowercased', () => {
        expect(VIBE_CODING_OAUTH_CLIENT_NAME_FRAGMENTS.length).toBeGreaterThan(0)
        for (const fragment of VIBE_CODING_OAUTH_CLIENT_NAME_FRAGMENTS) {
            expect(fragment).toBe(fragment.toLowerCase())
            expect(fragment.length).toBeGreaterThan(0)
        }
    })
})

describe('MCPClientProfile', () => {
    describe('isCodingAgent()', () => {
        it.each([['claude-code'], ['Codex CLI'], ['cline'], ['zed-editor'], ['GitHub Copilot Chat']])(
            'returns true for %s',
            (clientName) => {
                expect(new MCPClientProfile({ clientName }).isCodingAgent()).toBe(true)
            }
        )

        it.each([['Claude Desktop'], ['cursor'], ['mcp-inspector'], [''], ['   ']])(
            'returns false for %s',
            (clientName) => {
                expect(new MCPClientProfile({ clientName }).isCodingAgent()).toBe(false)
            }
        )

        it('returns false when clientName is undefined', () => {
            expect(new MCPClientProfile({}).isCodingAgent()).toBe(false)
        })
    })

    describe('isPostHogCodeConsumer()', () => {
        it('returns true for the exact consumer value', () => {
            expect(new MCPClientProfile({ consumer: POSTHOG_CODE_CONSUMER }).isPostHogCodeConsumer()).toBe(true)
        })

        it.each([['slack'], ['posthog'], ['PostHog-Code'], ['']])('returns false for %s', (consumer) => {
            expect(new MCPClientProfile({ consumer }).isPostHogCodeConsumer()).toBe(false)
        })

        it('returns false when consumer is undefined', () => {
            expect(new MCPClientProfile({}).isPostHogCodeConsumer()).toBe(false)
        })
    })

    describe('isVibeCodingClient()', () => {
        it.each([['Lovable'], ['lovable.dev'], ['Replit'], ['Replit Agent']])(
            'returns true for OAuth client name %s',
            (oauthClientName) => {
                expect(new MCPClientProfile({ oauthClientName }).isVibeCodingClient()).toBe(true)
            }
        )

        it.each([['Claude Code (posthog)'], ['Cursor'], [''], ['   ']])(
            'returns false for OAuth client name %s',
            (oauthClientName) => {
                expect(new MCPClientProfile({ oauthClientName }).isVibeCodingClient()).toBe(false)
            }
        )

        it('returns false when oauthClientName is undefined', () => {
            expect(new MCPClientProfile({}).isVibeCodingClient()).toBe(false)
        })

        it('uses oauthClientName, not the MCP clientName', () => {
            // A generic MCP client name should not trigger a match — only the
            // OAuth application name does, since vibe-coding platforms typically
            // wrap a generic MCP client.
            expect(
                new MCPClientProfile({ clientName: 'lovable', oauthClientName: 'Cursor' }).isVibeCodingClient()
            ).toBe(false)
            expect(
                new MCPClientProfile({ clientName: 'mcp-inspector', oauthClientName: 'Lovable' }).isVibeCodingClient()
            ).toBe(true)
        })
    })

    describe('capabilities.supportsInstructions', () => {
        it.each([['codex'], ['Codex'], ['CODEX'], ['codex-cli'], ['Codex CLI'], ['codex/1.2.3'], ['openai-codex']])(
            'is false for Codex variant %s',
            (clientName) => {
                expect(new MCPClientProfile({ clientName }).capabilities.supportsInstructions).toBe(false)
            }
        )

        it.each([
            ['claude-code'],
            ['Claude Code'],
            ['Claude Desktop'],
            ['cursor'],
            ['cline'],
            ['mcp-inspector'],
            ['windsurf'],
            ['zed'],
        ])('is true for non-Codex client %s', (clientName) => {
            expect(new MCPClientProfile({ clientName }).capabilities.supportsInstructions).toBe(true)
        })

        it.each([[undefined], [''], ['   ']])('defaults to true for %s', (clientName) => {
            expect(new MCPClientProfile({ clientName }).capabilities.supportsInstructions).toBe(true)
        })
    })

    it('caches capabilities across reads', () => {
        const profile = new MCPClientProfile({ clientName: 'codex' })
        expect(profile.capabilities).toBe(profile.capabilities)
    })

    it('exposes constructor inputs as readonly fields', () => {
        const profile = new MCPClientProfile({
            clientName: 'claude-code',
            clientVersion: '1.2.3',
            consumer: POSTHOG_CODE_CONSUMER,
            oauthClientName: 'Lovable',
        })
        expect(profile.clientName).toBe('claude-code')
        expect(profile.clientVersion).toBe('1.2.3')
        expect(profile.consumer).toBe(POSTHOG_CODE_CONSUMER)
        expect(profile.oauthClientName).toBe('Lovable')
    })
})

describe('DEFAULT_CLIENT_CAPABILITIES', () => {
    it('has supportsInstructions=true by default', () => {
        expect(DEFAULT_CLIENT_CAPABILITIES.supportsInstructions).toBe(true)
    })
})
