import { resolveToolCall, resolveToolKey } from './toolResolver'

describe('toolResolver', () => {
    describe('resolveToolKey', () => {
        it('parses the inner tool name out of a single-exec call command', () => {
            const resolved = resolveToolKey('posthog', 'exec', { command: 'call insight-create {"name":"Signups"}' })
            expect(resolved.resolvedKey).toEqual('insight-create')
            expect(resolved.innerToolName).toEqual('insight-create')
            expect(resolved.innerInput).toEqual({ name: 'Signups' })
        })

        it('parses --json single-exec call commands', () => {
            const resolved = resolveToolKey('posthog', 'exec', {
                command: 'call --json query-trends {"kind":"TrendsQuery"}',
            })
            expect(resolved.resolvedKey).toEqual('query-trends')
            expect(resolved.innerInput).toEqual({ kind: 'TrendsQuery' })
        })

        it('does not expose malformed single-exec arguments as valid empty input', () => {
            const resolved = resolveToolKey('posthog', 'exec', {
                command: 'call query-trends {not-json',
            })
            expect(resolved.resolvedKey).toEqual('query-trends')
            expect(resolved.innerToolName).toEqual('query-trends')
            expect(resolved.innerInput).toBeUndefined()
        })

        it('maps discovery verbs to sentinels', () => {
            expect(resolveToolKey('posthog', 'exec', { command: 'tools' }).resolvedKey).toEqual(
                '__posthog_exec_tools__'
            )
            expect(resolveToolKey('posthog', 'exec', { command: 'search recordings' }).resolvedKey).toEqual(
                '__posthog_exec_search__'
            )
        })

        it('falls back to unknown sentinel for malformed commands', () => {
            expect(resolveToolKey('posthog', 'exec', { command: '!!!' }).resolvedKey).toEqual(
                '__posthog_exec_unknown__'
            )
        })

        it.each([
            ['call --confirm feature-flag-delete {"key":"x"}'],
            ['call --json --confirm feature-flag-delete {"key":"x"}'],
            ['call --confirm --json feature-flag-delete {"key":"x"}'],
        ])('strips --json/--confirm flags in any order before the inner tool name (%s)', (command) => {
            const resolved = resolveToolKey('posthog', 'exec', { command })
            expect(resolved.resolvedKey).toEqual('feature-flag-delete')
            expect(resolved.innerToolName).toEqual('feature-flag-delete')
            expect(resolved.innerInput).toEqual({ key: 'x' })
        })

        it.each([['call'], ['call --json'], ['call --confirm --json']])(
            'falls back to unknown sentinel for a call with no resolvable sub-tool (%s)',
            (command) => {
                const resolved = resolveToolKey('posthog', 'exec', { command })
                expect(resolved.resolvedKey).toEqual('__posthog_exec_unknown__')
                expect(resolved.innerToolName).toBeUndefined()
            }
        )

        it('returns the wire name for non-exec MCP tools that carry one', () => {
            expect(resolveToolKey('user-mcp', 'do_thing', {}).resolvedKey).toEqual('do_thing')
        })

        it.each(['Edit', 'TodoWrite', 'Grep', 'Task'])(
            'falls back to the SDK %s name when the wire toolName is empty (every Claude built-in)',
            (sdkName) => {
                // Built-ins carry no top-level toolName on the wire — only `_meta.claudeCode.toolName`.
                expect(resolveToolKey('claude', '', {}, sdkName).resolvedKey).toEqual(sdkName)
            }
        )

        it('prefers the explicit wire toolName over the SDK name when both are present', () => {
            expect(resolveToolKey('user-mcp', 'do_thing', {}, 'Edit').resolvedKey).toEqual('do_thing')
        })

        it('resolves to empty string when neither a wire toolName nor an SDK name is present', () => {
            expect(resolveToolKey('claude', '', {}).resolvedKey).toEqual('')
        })
    })

    describe('resolveToolCall', () => {
        it('resolves a raw streamed exec invocation at render time', () => {
            expect(
                resolveToolCall({
                    rawServerName: 'posthog',
                    rawToolName: 'exec',
                    input: { command: 'call query-trends {"kind":"TrendsQuery"}' },
                })
            ).toEqual({
                resolvedKey: 'query-trends',
                innerToolName: 'query-trends',
                innerInput: { kind: 'TrendsQuery' },
                claudeToolName: undefined,
            })
        })

        it.each([
            { claudeCode: { toolName: 'mcp__posthog__exec' } },
            { posthog: { toolName: 'mcp__posthog__exec' } },
            { posthog: { mcp: { server: 'posthog', tool: 'exec' } } },
        ])('resolves exec invocations from adapter metadata %j', (meta) => {
            expect(
                resolveToolCall({
                    rawServerName: 'posthog',
                    rawToolName: '',
                    input: { command: 'call query-trends {"kind":"TrendsQuery","series":[]}' },
                    meta,
                })
            ).toEqual({
                resolvedKey: 'query-trends',
                innerToolName: 'query-trends',
                innerInput: { kind: 'TrendsQuery', series: [] },
                claudeToolName: meta.claudeCode?.toolName,
            })
        })

        it.each([
            [{ posthog: { mcp: { server: 'other', tool: 'exec' } } }, 'exec', 'mcp__other__exec'],
            [{ posthog: { toolName: 'mcp__other__exec' } }, 'exec', 'mcp__other__exec'],
            [
                { posthog: { toolName: 'mcp__posthog__exec', mcp: { server: 'other', tool: 'exec' } } },
                'exec',
                'mcp__other__exec',
            ],
            [{ claudeCode: { toolName: 'mcp__gitlab__clone_repo' } }, '', 'mcp__gitlab__clone_repo'],
            [{ posthog: { mcp: { server: 'gitlab', tool: 'list_repos' } } }, '', 'mcp__gitlab__list_repos'],
        ])('preserves external MCP identity from metadata %j', (meta, rawToolName, resolvedKey) => {
            expect(
                resolveToolCall({
                    rawServerName: 'posthog',
                    rawToolName,
                    input: { command: 'call query-trends {}' },
                    meta,
                })
            ).toMatchObject({ resolvedKey })
        })

        it('resolves a raw built-in invocation from metadata at render time', () => {
            expect(
                resolveToolCall({
                    rawServerName: 'claude',
                    rawToolName: '',
                    input: { file_path: 'app.ts' },
                    meta: { claudeCode: { toolName: 'Edit' } },
                })
            ).toEqual({
                resolvedKey: 'Edit',
                claudeToolName: 'Edit',
            })
        })
    })
})
