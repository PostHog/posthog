import { describe, expect, it } from 'vitest'

import {
    ANTHROPIC_CLIENT_NAME_FRAGMENTS,
    ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS,
    ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS,
    CODING_AGENT_CLIENT_NAME_FRAGMENTS,
    DEFAULT_CLIENT_CAPABILITIES,
    MCPClientProfile,
    POSTHOG_CODE_CONSUMER,
    TOOLS_MODE_CLIENT_NAME_FRAGMENTS,
    TOOLS_MODE_USER_AGENT_FRAGMENTS,
    isClaudeUiHostClient,
    isCliModeEnabledClient,
    isPostHogCodeConsumer,
    isToolsModeClient,
    resolveEffectiveClientName,
} from '@/lib/client-detection'

describe('isCliModeEnabledClient', () => {
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
            ['devin'],
            ['librechat'],
            ['notion'],
            ['opencode'],
            ['amp-mcp-client'],
            ['poke'],
            ['grok'],
            ['ando-mcp-gateway'],
        ])('returns true for %s', (clientName) => {
            expect(isCliModeEnabledClient(clientName)).toBe(true)
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
            ['LibreChat'],
            ['libre-chat'],
            ['LibreChat/1.2.3'],
            ['notion-mcp-client'],
            ['Notion'],
            ['Devin'],
            ['OpenCode'],
            ['opencode/1.2.3'],
            ['Amp MCP Client'],
            ['Poke'],
            ['Grok'],
            ['grok-build'],
            ['Grok/1.2.3'],
        ])('returns true for variant %s (case-insensitive substring match)', (clientName) => {
            expect(isCliModeEnabledClient(clientName)).toBe(true)
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
            expect(isCliModeEnabledClient(clientName)).toBe(false)
        })
    })

    describe('explicitly excluded clients', () => {
        // Cursor sends content[].text to the model and displays structuredContent in UI,
        // so the formatted-results suppression isn't needed. Guard against someone
        // adding it to the coding-agent list.
        it('returns false for cursor (intentionally excluded)', () => {
            expect(isCliModeEnabledClient('cursor')).toBe(false)
            expect(isCliModeEnabledClient('Cursor')).toBe(false)
            expect(isCliModeEnabledClient('cursor-editor')).toBe(false)
        })
    })

    describe('edge cases', () => {
        it('returns false for undefined', () => {
            expect(isCliModeEnabledClient(undefined)).toBe(false)
        })

        it('returns false for empty string', () => {
            expect(isCliModeEnabledClient('')).toBe(false)
        })

        it('treats whitespace-only as non-match', () => {
            expect(isCliModeEnabledClient('   ')).toBe(false)
        })
    })

    it('keeps the fragment list non-empty and lowercased', () => {
        expect(CODING_AGENT_CLIENT_NAME_FRAGMENTS.length).toBeGreaterThan(0)
        for (const fragment of CODING_AGENT_CLIENT_NAME_FRAGMENTS) {
            expect(fragment).toBe(fragment.toLowerCase())
            expect(fragment.length).toBeGreaterThan(0)
        }
    })

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
    it('matches the exact PostHog Code consumer value', () => {
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

describe('isToolsModeClient', () => {
    it.each([['cursor'], ['Cursor'], ['cursor-vscode'], ['cursor/1.2.3'], ['cursor-editor']])(
        'returns true for client name %s',
        (clientName) => {
            expect(isToolsModeClient(clientName)).toBe(true)
        }
    )

    it.each([
        // ChatGPT never self-reports a client name; the surface is UA-only.
        ['openai-mcp/1.0.0 (ChatGPT)'],
        // Older Cursor builds omit clientInfo.name and identify only via UA.
        ['Cursor/3.1.15 (darwin arm64)'],
    ])('returns true for the name-less user-agent %s', (userAgent) => {
        expect(isToolsModeClient(undefined, userAgent)).toBe(true)
    })

    it.each([['openai-mcp/1.0.0'], ['openai-mcp/1.0.0 (Codex)'], ['openai-mcp/1.0.0 (Agent Builder)']])(
        'returns false for the non-ChatGPT openai-mcp surface %s',
        (userAgent) => {
            expect(isToolsModeClient(undefined, userAgent)).toBe(false)
        }
    )

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

describe('isClaudeUiHostClient', () => {
    it.each([['ClaudeAI'], ['claudeai'], ['CLAUDEAI'], ['Anthropic/ClaudeAI']])(
        'returns true for vendor client %s',
        (vendorClient) => {
            expect(isClaudeUiHostClient({ vendorClient })).toBe(true)
        }
    )

    it.each([['Claude-User'], ['claude-user'], ['Claude_User']])('returns true for user agent %s', (userAgent) => {
        expect(isClaudeUiHostClient({ userAgent })).toBe(true)
    })

    it.each([['ClaudeCode'], ['some-random-tool'], ['']])('returns false for vendor client %s', (vendorClient) => {
        expect(isClaudeUiHostClient({ vendorClient })).toBe(false)
    })

    it('returns false when nothing matches', () => {
        expect(isClaudeUiHostClient({})).toBe(false)
        expect(isClaudeUiHostClient({ vendorClient: 'ClaudeCode', userAgent: 'node-fetch' })).toBe(false)
    })

    it('keeps the fragment lists non-empty and lowercased', () => {
        for (const fragments of [ANTHROPIC_UI_HOST_VENDOR_FRAGMENTS, ANTHROPIC_UI_HOST_USER_AGENT_FRAGMENTS]) {
            expect(fragments.length).toBeGreaterThan(0)
            for (const fragment of fragments) {
                expect(fragment).toBe(fragment.toLowerCase())
                expect(fragment.length).toBeGreaterThan(0)
            }
        }
    })
})

describe('MCPClientProfile', () => {
    describe('isCliModeEnabled()', () => {
        it.each([
            ['claude-code'],
            ['Claude Code'],
            ['claude-code-cli'],
            ['claude-code/1.2.3'],
            ['cline'],
            ['cline-bot'],
            ['continue'],
            ['codex'],
            ['Codex CLI'],
            ['windsurf'],
            ['zed'],
            ['zed-editor'],
            ['aider'],
            ['github.copilot'],
            ['GitHub Copilot Chat'],
            ['LibreChat'],
            ['libre-chat'],
            ['notion-mcp-client'],
        ])('returns true for %s', (clientName) => {
            expect(new MCPClientProfile({ clientName }).isCliModeEnabled()).toBe(true)
        })

        it.each([['Claude Desktop'], ['claude-desktop'], ['cursor'], ['mcp-inspector'], [''], ['   ']])(
            'returns false for %s',
            (clientName) => {
                expect(new MCPClientProfile({ clientName }).isCliModeEnabled()).toBe(false)
            }
        )

        it('returns false when clientName is undefined', () => {
            expect(new MCPClientProfile({}).isCliModeEnabled()).toBe(false)
        })

        describe('Anthropic vendor client', () => {
            it.each([['ClaudeCode'], ['ClaudeAI'], ['Cowork'], ['Anthropic/ClaudeAI']])(
                'enables CLI mode for known Anthropic client %s regardless of clientName',
                (vendorClient) => {
                    // Anthropic pools MCP transports across all its products and
                    // reports the live one in `x-anthropic-client`. Every known
                    // Anthropic client runs in CLI mode, even when the initialize
                    // body's clientName looks non-coding (e.g. the pool owner).
                    expect(
                        new MCPClientProfile({ clientName: 'Claude Desktop', vendorClient }).isCliModeEnabled()
                    ).toBe(true)
                }
            )

            it('does not enable CLI mode for an unknown vendorClient value', () => {
                // Detection matches the known-header list, not mere presence.
                expect(
                    new MCPClientProfile({
                        clientName: 'Claude Desktop',
                        vendorClient: 'SomeUnknownClient',
                    }).isCliModeEnabled()
                ).toBe(false)
            })

            it('falls back to clientName for coding agents when vendorClient is unknown', () => {
                expect(
                    new MCPClientProfile({
                        clientName: 'claude-code',
                        vendorClient: 'SomeUnknownClient',
                    }).isCliModeEnabled()
                ).toBe(true)
            })

            it('falls back to clientName when vendorClient is missing', () => {
                expect(new MCPClientProfile({ clientName: 'claude-code' }).isCliModeEnabled()).toBe(true)
            })

            it('uses clientName for non-Anthropic clients (no vendorClient)', () => {
                expect(new MCPClientProfile({ clientName: 'Claude Desktop' }).isCliModeEnabled()).toBe(false)
            })

            it('enables CLI mode for the ClaudeDesign vendor header', () => {
                expect(new MCPClientProfile({ vendorClient: 'ClaudeDesign' }).isCliModeEnabled()).toBe(true)
            })

            it.each([['Claude-User'], ['claude-user'], ['Claude_User']])(
                'enables CLI mode via the %s user-agent when the vendor header is absent',
                (userAgent) => {
                    // Claude.ai web/desktop and some internal Anthropic tools connect
                    // without x-anthropic-client, identifying only via this user-agent.
                    expect(new MCPClientProfile({ userAgent }).isCliModeEnabled()).toBe(true)
                }
            )

            it.each([['Anthropic/ClaudeAI'], ['Anthropic/Toolbox'], ['anthropic/claudeai']])(
                'enables CLI mode via the pooled %s clientInfo.name when the vendor header is absent',
                (clientName) => {
                    // Header-less Anthropic sessions report only the pooled Anthropic/*
                    // pool-owner name. Matching it for CLI mode is safe (unlike UI-host
                    // detection) because every Anthropic product belongs in CLI mode.
                    expect(new MCPClientProfile({ clientName }).isCliModeEnabled()).toBe(true)
                }
            )
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

    describe('isClaudeUiHost()', () => {
        it('returns true for Claude web/desktop vendor client (x-anthropic-client: ClaudeAI)', () => {
            expect(new MCPClientProfile({ vendorClient: 'ClaudeAI' }).isClaudeUiHost()).toBe(true)
        })

        it('returns true via User-Agent (Claude-User) when the vendor header is absent', () => {
            expect(new MCPClientProfile({ userAgent: 'Claude-User' }).isClaudeUiHost()).toBe(true)
        })

        it('returns false for Claude Code (vendorClient: ClaudeCode)', () => {
            expect(new MCPClientProfile({ vendorClient: 'ClaudeCode' }).isClaudeUiHost()).toBe(false)
        })

        it('returns true for Cowork (vendorClient: Cowork)', () => {
            expect(new MCPClientProfile({ vendorClient: 'Cowork' }).isClaudeUiHost()).toBe(true)
        })

        it('vendor client wins over a shared Claude-User user-agent', () => {
            // Claude Code can share the `Claude-User` user-agent with web/desktop,
            // but its vendor client is authoritative and excludes it.
            expect(
                new MCPClientProfile({ vendorClient: 'ClaudeCode', userAgent: 'Claude-User' }).isClaudeUiHost()
            ).toBe(false)
        })

        it('does not match the pooled clientName alone — avoids misclassifying Claude Code', () => {
            // Claude Code's pooled initialize body also says `Anthropic/ClaudeAI`;
            // only the per-request vendor client / user-agent identify a UI host.
            expect(new MCPClientProfile({ clientName: 'Anthropic/ClaudeAI' }).isClaudeUiHost()).toBe(false)
            expect(
                new MCPClientProfile({ clientName: 'Anthropic/ClaudeAI', vendorClient: 'ClaudeCode' }).isClaudeUiHost()
            ).toBe(false)
        })

        it('returns false when nothing is set', () => {
            expect(new MCPClientProfile({}).isClaudeUiHost()).toBe(false)
        })

        it('Claude Code stays a coding agent and is not a UI host', () => {
            const profile = new MCPClientProfile({ clientName: 'Anthropic/ClaudeAI', vendorClient: 'ClaudeCode' })
            expect(profile.isCliModeEnabled()).toBe(true)
            expect(profile.isClaudeUiHost()).toBe(false)
        })
    })

    describe('isInlineExecUiHost()', () => {
        it.each([['ClaudeCode'], ['Cowork']])('is true for the %s vendor client', (vendorClient) => {
            expect(new MCPClientProfile({ vendorClient }).isInlineExecUiHost()).toBe(true)
        })

        // Claude.ai renders via the separate render-ui tool, not the inline exec payload.
        it.each([['ClaudeAI'], ['ClaudeDesign'], ['some-random-tool'], ['']])(
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
            clientVersion: '1.2.3',
            consumer: POSTHOG_CODE_CONSUMER,
            oauthClientName: 'Lovable',
            vendorClient: 'ClaudeCode',
            userAgent: 'Claude-User',
        })
        expect(profile.clientName).toBe('claude-code')
        expect(profile.clientVersion).toBe('1.2.3')
        expect(profile.consumer).toBe(POSTHOG_CODE_CONSUMER)
        expect(profile.oauthClientName).toBe('Lovable')
        expect(profile.vendorClient).toBe('ClaudeCode')
        expect(profile.userAgent).toBe('Claude-User')
    })
})

describe('DEFAULT_CLIENT_CAPABILITIES', () => {
    it('has supportsInstructions=true by default', () => {
        expect(DEFAULT_CLIENT_CAPABILITIES.supportsInstructions).toBe(true)
    })
})
