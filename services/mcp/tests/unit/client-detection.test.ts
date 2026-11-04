import { describe, expect, it } from 'vitest'

import {
    ANTHROPIC_CLIENT_NAME_FRAGMENTS,
    ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS,
    ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS,
    DEFAULT_CLIENT_CAPABILITIES,
    MCPClientProfile,
    OPENAI_RENDER_UI_CLIENT_NAMES,
    POSTHOG_CODE_CONSUMER,
    TOOLS_MODE_CLIENT_NAME_FRAGMENTS,
    TOOLS_MODE_USER_AGENT_FRAGMENTS,
    isLegacyDialectOnlyClient,
    isPostHogCodeConsumer,
    isToolsModeClient,
    resolveEffectiveClientName,
} from '@/lib/client-detection'

describe('ANTHROPIC_CLIENT_NAME_FRAGMENTS', () => {
    it('keeps the Anthropic client fragment list non-empty, lowercased, and separator-free', () => {
        // Fragments are compared against the normalized header value (separators
        // stripped, lowercased), so they must be pre-normalized to match.
        expect(ANTHROPIC_CLIENT_NAME_FRAGMENTS.length).toBeGreaterThan(0)
        for (const fragment of ANTHROPIC_CLIENT_NAME_FRAGMENTS) {
            expect(fragment).toBe(fragment.toLowerCase().replace(/[-_\s]+/g, ''))
            expect(fragment.length).toBeGreaterThan(0)
        }
    })
})

describe('resolveEffectiveClientName', () => {
    it('prefers the self-reported clientName when present', () => {
        expect(resolveEffectiveClientName('Cursor', 'ClaudeCode')).toBe('Cursor')
        expect(resolveEffectiveClientName('claude-code', undefined)).toBe('claude-code')
    })

    it.each([
        ['ClaudeCode', 'claude-code'],
        ['ClaudeAI', 'claude-ai'],
        ['Cowork', 'cowork'],
        ['ClaudeDesign', 'claude-design'],
        // Case- and separator-insensitive, matching normalizeClientName.
        ['claudecode', 'claude-code'],
        ['CLAUDE-CODE', 'claude-code'],
    ])('maps vendor header %s to %s when clientName is absent', (vendorClient, expected) => {
        expect(resolveEffectiveClientName(undefined, vendorClient)).toBe(expected)
    })

    it('keeps an unrecognized vendor value rather than dropping it', () => {
        expect(resolveEffectiveClientName(undefined, 'SomeFutureAnthropicProduct')).toBe('SomeFutureAnthropicProduct')
    })

    it('returns undefined when neither clientName nor vendorClient is set', () => {
        expect(resolveEffectiveClientName(undefined, undefined)).toBeUndefined()
        expect(resolveEffectiveClientName('', undefined)).toBeUndefined()
    })

    it('falls back to the vendor header when clientName is empty', () => {
        expect(resolveEffectiveClientName('', 'ClaudeCode')).toBe('claude-code')
    })
})

describe('isPostHogCodeConsumer', () => {
    it('matches the exact PostHog Desktop consumer value', () => {
        expect(isPostHogCodeConsumer(POSTHOG_CODE_CONSUMER)).toBe(true)
        expect(isPostHogCodeConsumer('posthog-code')).toBe(true)
    })

    it.each([['posthog_code'], ['PostHog-Code'], ['posthog-code-v2'], ['posthog'], ['slack'], ['posthog_ai'], ['']])(
        'returns false for %s (must be exact match — posthog_ai is not a UI-apps host)',
        (consumer) => {
            expect(isPostHogCodeConsumer(consumer)).toBe(false)
        }
    )

    it('returns false for undefined', () => {
        expect(isPostHogCodeConsumer(undefined)).toBe(false)
    })
})

describe('isLegacyDialectOnlyClient', () => {
    it.each([
        ['antigravity-client'],
        ['antigravity'],
        ['Antigravity'],
        ['antigravity-client/1.2.3'],
        // Bridge variants are gated too: their fallback lands on the legacy
        // handshake, which works, while their stateless support varies by version.
        ['antigravity-client (via mcp-remote 0.1.37)'],
    ])('returns true for %s', (clientName) => {
        expect(isLegacyDialectOnlyClient(clientName)).toBe(true)
    })

    it.each([['claude-code'], ['cursor'], ['mcp-remote-fallback-test'], [''], [undefined]])(
        'returns false for %s',
        (clientName) => {
            expect(isLegacyDialectOnlyClient(clientName)).toBe(false)
        }
    )
})

describe('isToolsModeClient', () => {
    it.each([['cursor'], ['Cursor'], ['cursor-vscode'], ['cursor/1.2.3'], ['cursor-editor']])(
        'returns true for client name %s',
        (clientName) => {
            expect(isToolsModeClient(clientName)).toBe(true)
        }
    )

    // Older Cursor builds omit clientInfo.name and identify only via UA.
    it('returns true for the name-less Cursor user-agent', () => {
        expect(isToolsModeClient(undefined, 'Cursor/3.1.15 (darwin arm64)')).toBe(true)
    })

    // OpenAI's proxy caches the roster it captures for a published plugin, so a
    // labeled ChatGPT request landing in tools mode would freeze the full roster
    // for every plugin user. Every openai-mcp surface stays on the cli default.
    it.each([
        ['openai-mcp/1.0.0'],
        ['openai-mcp/1.0.0 (ChatGPT)'],
        ['openai-mcp/1.0.0 (Codex)'],
        ['openai-mcp/1.0.0 (Agent Builder)'],
    ])('returns false for the openai-mcp surface %s', (userAgent) => {
        expect(isToolsModeClient(undefined, userAgent)).toBe(false)
    })

    it.each([['claude-code'], ['mcp-inspector'], ['some-random-tool'], [''], [undefined]])(
        'returns false for client name %s',
        (clientName) => {
            expect(isToolsModeClient(clientName)).toBe(false)
        }
    )

    it('keeps the fragment lists non-empty and lowercased', () => {
        for (const fragments of [TOOLS_MODE_CLIENT_NAME_FRAGMENTS, TOOLS_MODE_USER_AGENT_FRAGMENTS]) {
            expect(fragments.length).toBeGreaterThan(0)
            for (const fragment of fragments) {
                expect(fragment).toBe(fragment.toLowerCase())
                expect(fragment.length).toBeGreaterThan(0)
            }
        }
    })
})

describe('MCPClientProfile', () => {
    describe('prefersFormattedText()', () => {
        // The default: a client nobody has classified reads text only, so it gets the
        // formatted table without the duplicate structured copy.
        it.each([['codex-mcp-client'], ['opencode'], ['some-new-agent'], ['Claude Desktop'], ['']])(
            'returns true for text client %s',
            (clientName) => {
                expect(new MCPClientProfile({ clientName }).prefersFormattedText()).toBe(true)
            }
        )

        it('returns true when the client sends no identity at all', () => {
            expect(new MCPClientProfile({}).prefersFormattedText()).toBe(true)
        })

        it.each([
            [{ clientName: 'cursor-vscode' }],
            [{ userAgent: 'Cursor/3.1.15 (darwin arm64)' }],
            [{ clientName: 'openai-mcp' }],
            [{ clientName: 'some-new-agent', uiSupported: true }],
        ])('returns false for a client that renders structuredContent: %o', (input) => {
            expect(new MCPClientProfile(input).prefersFormattedText()).toBe(false)
        })

        it('returns true for a known render-ui host that declares no MCP Apps support', () => {
            expect(new MCPClientProfile({ clientName: 'openai-mcp', uiSupported: false }).prefersFormattedText()).toBe(
                true
            )
        })

        it.each([
            [{ vendorClient: 'ClaudeCode' }],
            [{ vendorClient: 'ClaudeAI' }],
            [{ vendorClient: 'Cowork' }],
            [{ userAgent: 'Claude-User' }],
            [{ clientName: 'Anthropic/ClaudeAI' }],
        ])('returns true for Anthropic client %o, including render-ui hosts', (input) => {
            expect(new MCPClientProfile(input).prefersFormattedText()).toBe(true)
        })
    })

    describe('isPostHogCodeConsumer()', () => {
        it('returns true for the exact consumer value', () => {
            expect(new MCPClientProfile({ consumer: POSTHOG_CODE_CONSUMER }).isPostHogCodeConsumer()).toBe(true)
        })

        it.each([['slack'], ['posthog'], ['PostHog-Code'], ['posthog_ai'], ['']])(
            'returns false for %s',
            (consumer) => {
                expect(new MCPClientProfile({ consumer }).isPostHogCodeConsumer()).toBe(false)
            }
        )

        it('returns false when consumer is undefined', () => {
            expect(new MCPClientProfile({}).isPostHogCodeConsumer()).toBe(false)
        })
    })

    describe('isToolsModeClient()', () => {
        it('does not match the vendor header — Anthropic pooled transports stay in cli mode', () => {
            // Only the self-reported name and the user-agent participate; a vendor
            // value that happened to contain a tools-mode fragment must not match.
            expect(new MCPClientProfile({ vendorClient: 'cursor' }).isToolsModeClient()).toBe(false)
            expect(new MCPClientProfile({ vendorClient: 'ClaudeCode', clientName: 'cursor' }).isToolsModeClient()).toBe(
                true
            )
        })
    })

    describe('isRenderUiHost()', () => {
        it.each([
            { vendorClient: 'ClaudeAI' },
            { vendorClient: 'CLAUDEAI' },
            { vendorClient: 'Anthropic/ClaudeAI' },
            { vendorClient: 'Cowork' },
            { userAgent: 'Claude-User' },
            { userAgent: 'Claude_User' },
        ])('returns true for Claude web/desktop and Cowork: %j', (input) => {
            expect(new MCPClientProfile(input).isRenderUiHost()).toBe(true)
        })

        it.each([
            {},
            { vendorClient: 'ClaudeCode' },
            { vendorClient: 'some-random-tool' },
            { vendorClient: 'ClaudeCode', userAgent: 'node-fetch' },
            // The vendor client is authoritative, so Claude Code stays excluded when it
            // shares the `Claude-User` user-agent with web/desktop.
            { vendorClient: 'ClaudeCode', userAgent: 'Claude-User' },
            // Claude Code's pooled initialize body also says `Anthropic/ClaudeAI`.
            { clientName: 'Anthropic/ClaudeAI' },
            { clientName: 'Anthropic/ClaudeAI', vendorClient: 'ClaudeCode' },
        ])('returns false for %j', (input) => {
            expect(new MCPClientProfile(input).isRenderUiHost()).toBe(false)
        })

        it('follows the MCP Apps declaration from the Claude desktop Code tab', () => {
            const profile = new MCPClientProfile({
                userAgent: 'claude-code/2.1.309 (claude-desktop, agent-sdk/0.3.309)',
                uiSupported: true,
            })
            expect(profile.isRenderUiHost()).toBe(true)
        })

        it('Claude Code prefers formatted text and is not a UI host', () => {
            const profile = new MCPClientProfile({ clientName: 'Anthropic/ClaudeAI', vendorClient: 'ClaudeCode' })
            expect(profile.prefersFormattedText()).toBe(true)
            expect(profile.isRenderUiHost()).toBe(false)
        })

        it('keeps the fragment lists non-empty and lowercased', () => {
            for (const fragments of [
                ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS,
                ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS,
                OPENAI_RENDER_UI_CLIENT_NAMES,
            ]) {
                expect(fragments.length).toBeGreaterThan(0)
                for (const fragment of fragments) {
                    expect(fragment).toBe(fragment.toLowerCase())
                    expect(fragment.length).toBeGreaterThan(0)
                }
            }
        })
    })

    describe('isInlineExecUiHost()', () => {
        it('is true for the ClaudeCode vendor client', () => {
            expect(new MCPClientProfile({ vendorClient: 'ClaudeCode' }).isInlineExecUiHost()).toBe(true)
        })

        // Claude.ai and Cowork render via the separate render-ui tool, not the inline exec payload.
        it.each([['ClaudeAI'], ['Cowork'], ['ClaudeDesign'], ['some-random-tool'], ['']])(
            'is false for the %s vendor client',
            (vendorClient) => {
                expect(new MCPClientProfile({ vendorClient }).isInlineExecUiHost()).toBe(false)
            }
        )

        it('is false when no vendor client is set (the user-agent is not a fallback here)', () => {
            expect(new MCPClientProfile({ userAgent: 'Claude-User' }).isInlineExecUiHost()).toBe(false)
        })
    })

    describe('isClaudeChatHost()', () => {
        it.each([
            // Claude web/desktop ignore the `instructions` payload → keep env-context.
            [{ vendorClient: 'ClaudeAI' }, true],
            // Vendor header absent → predominantly chat sessions, keep the UA fallback.
            [{ userAgent: 'Claude-User' }, true],
            // Cowork surfaces instructions normally → a UI host but not a chat host.
            [{ vendorClient: 'Cowork' }, false],
            [{ vendorClient: 'Cowork', userAgent: 'Claude-User' }, false],
            [{ vendorClient: 'ClaudeCode', userAgent: 'Claude-User' }, false],
            [{}, false],
        ])('resolves %j to %s', (input, expected) => {
            expect(new MCPClientProfile(input).isClaudeChatHost()).toBe(expected)
        })
    })

    describe('isAnthropicConnector()', () => {
        it.each([
            [{ clientName: 'Anthropic/ClaudeAI', userAgent: 'Claude-User' }, true],
            [{ clientName: 'Anthropic/ClaudeAI', vendorClient: 'ClaudeCode', userAgent: 'Claude-User' }, true],
            [{ clientName: 'Anthropic/ClaudeAI', vendorClient: 'Cowork', userAgent: 'Claude-User' }, true],
            [{ vendorClient: 'ClaudeAI', userAgent: 'Claude-User' }, true],
            [{ clientName: 'claude-code', vendorClient: 'ClaudeCode' }, false],
            [{ vendorClient: 'ClaudeCode' }, false],
            [{}, false],
        ])('resolves %j to %s', (input, expected) => {
            expect(new MCPClientProfile(input).isAnthropicConnector()).toBe(expected)
        })
    })

    describe('capabilities.supportsInstructions', () => {
        it.each([['codex'], ['Codex'], ['CODEX'], ['codex-cli'], ['Codex CLI'], ['codex/1.2.3'], ['openai-codex']])(
            'is false for Codex variant %s',
            (clientName) => {
                expect(new MCPClientProfile({ clientName }).capabilities.supportsInstructions).toBe(false)
            }
        )

        it('is false for the name-less Codex surface of openai-mcp (User-Agent only)', () => {
            expect(
                new MCPClientProfile({ userAgent: 'openai-mcp/1.0.0 (Codex)' }).capabilities.supportsInstructions
            ).toBe(false)
        })

        it.each([['openai-mcp/1.0.0'], ['openai-mcp/1.0.0 (ChatGPT)']])(
            'stays true for the non-Codex openai-mcp user-agent %s',
            (userAgent) => {
                expect(new MCPClientProfile({ userAgent }).capabilities.supportsInstructions).toBe(true)
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
            consumer: POSTHOG_CODE_CONSUMER,
            vendorClient: 'ClaudeCode',
            userAgent: 'Claude-User',
        })
        expect(profile.clientName).toBe('claude-code')
        expect(profile.consumer).toBe(POSTHOG_CODE_CONSUMER)
        expect(profile.vendorClient).toBe('ClaudeCode')
        expect(profile.userAgent).toBe('Claude-User')
    })
})

describe('DEFAULT_CLIENT_CAPABILITIES', () => {
    it('has supportsInstructions=true by default', () => {
        expect(DEFAULT_CLIENT_CAPABILITIES.supportsInstructions).toBe(true)
    })
})
