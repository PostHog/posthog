import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { ToolCallCard } from './ToolCallCard'
import { lookupToolRenderer, registerToolRenderers, toolRegistry, type ToolRegistryEntry } from './toolRegistry'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'Edit',
        rawServerName: 'posthog',
        rawToolName: '',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('toolRegistry', () => {
    // Product-specific data-tool renderers (insight/dashboard/recordings/error-tracking/query/notebook)
    // are NOT registered by this shared registry — they're contributed by scenes/max via
    // `registerMaxToolRenderers` and covered by that module's own test. Here we assert only what the
    // shared, Max-free registry registers: built-ins, exec verbs, the question card, and the fallback.

    it('bulk-registers every entry it is handed', () => {
        const Renderer = (() => null) as unknown as ToolRegistryEntry['Renderer']
        const icon = null as unknown as JSX.Element
        registerToolRenderers([
            { key: '__test_alpha__', displayName: 'Alpha', icon, Renderer },
            { key: '__test_beta__', displayName: 'Beta', icon, Renderer },
        ])
        expect(toolRegistry.lookup('__test_alpha__')?.displayName).toEqual('Alpha')
        expect(toolRegistry.lookup('__test_beta__')?.displayName).toEqual('Beta')
    })

    it('leaves product-specific and unknown tool names unregistered, resolving to the key as displayName', () => {
        expect(toolRegistry.lookup('mcp__user-installed__something')).toBeNull()
        // The synthesized fallback uses the resolved key as its displayName.
        expect(lookupToolRenderer('mcp__user-installed__something').displayName).toEqual(
            'mcp__user-installed__something'
        )
        expect(lookupToolRenderer('experiment-create').displayName).toEqual('experiment-create')
        // Product adapters live in scenes/max now, so the bare registry resolves them to the fallback.
        expect(toolRegistry.lookup('insight-create')).toBeNull()
        expect(toolRegistry.lookup('query-trends')).toBeNull()
        expect(toolRegistry.lookup('insight-query')).toBeNull()
        expect(toolRegistry.lookup('read_insight')).toBeNull()
        expect(toolRegistry.lookup('query-llm-trace')).toBeNull()
    })

    // Claude built-ins are keyed by their stable SDK name; the registry contributes a friendly
    // displayName + icon (not the wrench fallback's key/wrench).
    const builtinCases: [string, string][] = [
        ['Read', 'Read'],
        ['NotebookRead', 'Read'],
        ['Edit', 'Edit'],
        ['Write', 'Edit'],
        ['NotebookEdit', 'Edit'],
        ['MultiEdit', 'Edit'],
        ['Grep', 'Search'],
        ['Glob', 'Search'],
        ['LS', 'Search'],
        ['Bash', 'Terminal'],
        ['BashOutput', 'Terminal'],
        ['KillShell', 'Terminal'],
        ['WebSearch', 'Web'],
        ['WebFetch', 'Web'],
        ['Task', 'Subagent'],
        ['Agent', 'Subagent'],
        ['TaskCreate', 'Tasks'],
        ['TodoWrite', 'Tasks'],
        ['Skill', 'Skill'],
        ['ToolSearch', 'Tool search'],
        ['ExitPlanMode', 'Plan'],
        ['AskUserQuestion', 'Question'],
    ]

    it.each(builtinCases)('resolves built-in %s to a registered entry with displayName "%s"', (key, displayName) => {
        const entry = toolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
        expect(lookupToolRenderer(key).displayName).toEqual(displayName)
    })

    // PostHog single-exec discovery verbs are keyed by their sentinel key (from `resolveToolKey`); the
    // registry gives each a fitting icon + displayName instead of the wrench fallback.
    const execVerbCases: [string, string][] = [
        ['__posthog_exec_tools__', 'List tools'],
        ['__posthog_exec_search__', 'Search tools'],
        ['__posthog_exec_info__', 'Read tool'],
        ['__posthog_exec_schema__', 'Inspect schema'],
        ['__posthog_exec_unknown__', 'Run command'],
    ]

    it.each(execVerbCases)('resolves exec verb %s to a registered entry with displayName "%s"', (key, displayName) => {
        const entry = toolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
        expect(lookupToolRenderer(key).displayName).toEqual(displayName)
    })

    it('falls back to the wrench card (key as displayName) for an unmapped built-in-looking name', () => {
        expect(toolRegistry.lookup('NotARealTool')).toBeNull()
        expect(lookupToolRenderer('NotARealTool').displayName).toEqual('NotARealTool')
    })

    // Render-level: ToolCallCard resolves the entry, loads the lazy renderer behind a Suspense
    // skeleton, and the resolved renderer reaches the screen. The skeleton shows the displayName first.
    describe('lazy dispatch', () => {
        it('renders a Bash call through its dedicated card once the chunk loads', async () => {
            render(
                <ToolCallCard
                    message={makeMessage({
                        resolvedKey: 'Bash',
                        claudeToolName: 'Bash',
                        rawInput: { command: 'echo hello-bash' },
                    })}
                />
            )
            // Skeleton first (registry displayName), then the resolved card with the command. The
            // generous timeout covers jest compiling the lazy chunk's heavy deps on first load.
            expect(screen.getByText('Terminal')).toBeInTheDocument()
            expect(await screen.findByText('echo hello-bash', {}, { timeout: 10000 })).toBeInTheDocument()
        })

        it('renders an unmapped MCP tool through the generic card', async () => {
            render(
                <ToolCallCard
                    message={makeMessage({
                        resolvedKey: 'do_thing',
                        rawServerName: 'user-mcp',
                        rawToolName: 'do_thing',
                    })}
                />
            )
            expect(
                await screen.findByText('Call user-mcp – do_thing (MCP)', {}, { timeout: 10000 })
            ).toBeInTheDocument()
        })
    })
})
