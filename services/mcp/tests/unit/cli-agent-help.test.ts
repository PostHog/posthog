import { describe, expect, it } from 'vitest'

import { buildAgentHelp, toCliSyntax } from '@/cli/agent-help'
import { getCliTools } from '@/cli/tools'

describe('CLI agent help', () => {
    it('rewrites exec invocations to CLI syntax', () => {
        expect(toCliSyntax('posthog:exec({ "command": "search dashboard" })')).toBe('posthog-cli api search dashboard')
        expect(toCliSyntax('posthog:exec({ "command": "tools" })')).toBe('posthog-cli api tools')
    })

    it('quotes JSON payloads and unescapes embedded quotes', () => {
        expect(
            toCliSyntax(
                'posthog:exec({ "command": "call read-data-schema {\\"query\\": {\\"kind\\": \\"events\\"}}" })'
            )
        ).toBe(`posthog-cli api call read-data-schema '{"query": {"kind": "events"}}'`)
    })

    it('builds the agent guide from the MCP exec templates', () => {
        const help = buildAgentHelp(getCliTools())

        expect(help).toContain('posthog-cli api info <tool_name>')
        expect(help).toContain('SCHEMA DRILL-DOWN RULE')
        expect(help).not.toContain('posthog:exec(')
        expect(help).toContain('POSTHOG_CLI_EXPERIMENTAL_API')
        // Tool-domain index and query-tool catalog come from the bundled registry.
        expect(help).toContain('query-trends')
    })

    it('does not require credentials to build', () => {
        expect(() => buildAgentHelp(getCliTools())).not.toThrow()
    })

    it('hides AI-consent tools unless consent is confirmed', () => {
        const withoutConsent = getCliTools().map((tool) => tool.name)
        const withConsent = getCliTools({ aiConsentGiven: true }).map((tool) => tool.name)

        expect(withoutConsent).not.toContain('llma-summarization-create')
        expect(withConsent).toContain('llma-summarization-create')
    })
})
