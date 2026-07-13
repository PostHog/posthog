import { describe, expect, it, vi } from 'vitest'

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
        // The CLI always ships the code-execution verbs (spec §4.8), so the
        // guide must document the run/apply contract.
        expect(help).toContain('run <typescript source>')
        expect(help).toContain('apply <plan-id>')
        expect(help).not.toContain('posthog:exec(')
        // Tool-domain index and query-tool catalog come from the bundled registry.
        expect(help).toContain('query-trends')
    })

    it('does not require credentials to build', () => {
        expect(() => buildAgentHelp(getCliTools())).not.toThrow()
    })

    it('skips unavailable tools without stderr warnings', () => {
        const stderrWrite = vi.spyOn(process.stderr, 'write').mockImplementation(() => true)

        try {
            const toolNames = getCliTools().map((tool) => tool.name)

            expect(toolNames).not.toContain('evaluations-get')
            expect(stderrWrite).not.toHaveBeenCalled()
        } finally {
            stderrWrite.mockRestore()
        }
    })

    it('hides AI-consent tools unless consent is confirmed', () => {
        const withoutConsent = getCliTools().map((tool) => tool.name)
        const withConsent = getCliTools({ aiConsentGiven: true }).map((tool) => tool.name)

        expect(withoutConsent).not.toContain('llma-summarization-create')
        expect(withConsent).toContain('llma-summarization-create')
    })
})
