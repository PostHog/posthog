import { APP_COMMANDS, buildSlashCommands, filterSlashCommands, parseSlashCommand } from './slashCommands'

describe('slashCommands', () => {
    const agentCommands = [
        { name: 'clear', description: 'Clear conversation history' },
        { name: 'compact', description: 'Compact the conversation' },
        { name: 'init', description: 'Initialize a CLAUDE.md file' },
        { name: 'security-review', description: 'Review the branch' },
        { name: 'mcp:posthog:query', description: 'MCP prompt' },
        { name: 'usage', description: 'Show plan usage limits' },
        { name: 'querying-posthog-data', description: 'Query PostHog data', hint: 'question' },
    ]

    it('keeps clear, compact, and skills from the agent, and hides harness built-ins', () => {
        const commands = buildSlashCommands(APP_COMMANDS, agentCommands)
        const agentNames = commands.filter((c) => c.source === 'agent').map((c) => c.name)

        expect(agentNames).toEqual(['clear', 'compact', 'querying-posthog-data'])
        // The app /usage wins over the agent's /usage, and appears once.
        expect(commands.filter((c) => c.name === 'usage')).toEqual([expect.objectContaining({ source: 'app' })])
    })

    it.each([
        ['/', 'all commands', ['btw', 'good', 'bad', 'feedback', 'usage', 'ticket', 'clear', 'compact']],
        ['/co', 'name-prefix matches before description matches', ['compact', 'btw', 'usage', 'clear']],
        ['/COM', 'case-insensitive', ['compact']],
        ['/compact ', 'nothing once arguments start', []],
        ['hello /compact', 'nothing when the draft does not start with a slash', []],
    ])('filters %j to %s', (draft, _label, expected) => {
        const commands = buildSlashCommands(APP_COMMANDS, agentCommands.slice(0, 2))

        expect(filterSlashCommands(commands, draft).map((c) => c.name)).toEqual(expected)
    })

    it.each([
        ['/btw what is this?', { name: 'btw', args: 'what is this?' }],
        ['  /usage  ', { name: 'usage', args: '' }],
        ['/feedback line one\nline two', { name: 'feedback', args: 'line one\nline two' }],
        ['what does /btw do', null],
        ['/', null],
    ])('parses %j', (text, expected) => {
        expect(parseSlashCommand(text)).toEqual(expected)
    })
})
