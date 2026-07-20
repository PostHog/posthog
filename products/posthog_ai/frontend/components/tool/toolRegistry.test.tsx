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
    // The base registry module registers only built-ins, exec verbs, the question card, and the fallback.
    // The PostHog product data-tools self-register via `widgets/registerDataToolRenderers`, which
    // `ToolCallCard` side-effect-imports — and this file imports `ToolCallCard`, so those keys resolve here
    // too. Genuinely unmapped keys still fall through to the wrench card.

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

    it('resolves product data-tools because importing ToolCallCard self-registers them', () => {
        // Guards the fix: if the `registerDataToolRenderers` side-effect import is dropped from ToolCallCard,
        // these keys fall through to the generic JSON card instead of their widgets.
        expect(toolRegistry.lookup('insight-create')?.displayName).toEqual('Insight')
        expect(toolRegistry.lookup('query-trends')?.displayName).toEqual('Trends query')
    })

    it('falls back to the key as displayName for unknown and unmapped tool names', () => {
        expect(toolRegistry.lookup('mcp__user-installed__something')).toBeNull()
        // The synthesized fallback uses the resolved key as its displayName.
        expect(lookupToolRenderer('mcp__user-installed__something', false).displayName).toEqual(
            'mcp__user-installed__something'
        )
        expect(lookupToolRenderer('experiment-create', false).displayName).toEqual('experiment-create')
        // Never-registered keys (not built-ins, not any product data-tool) resolve to the fallback.
        expect(toolRegistry.lookup('insight-query')).toBeNull()
        expect(toolRegistry.lookup('read_insight')).toBeNull()
        expect(toolRegistry.lookup('query-llm-trace')).toBeNull()
    })

    // A user-installed MCP server can expose a tool whose bare name collides with a product-widget key
    // (e.g. "notebooks-create") and return an arbitrary `_posthogUrl`. Such a call is NOT from the
    // trusted single-exec PostHog server (no inner tool name was parsed, so `fromPostHogExec` is false),
    // and must fall through to the generic card rather than spoofing a first-party Notebook/Dashboard card.
    it.each([
        ['notebooks-create', 'Notebook'],
        ['dashboard-create', 'Dashboard'],
        ['query-trends', 'Trends query'],
    ])('gates product widget %s on a trusted PostHog-exec origin', (key, displayName) => {
        expect(lookupToolRenderer(key, false).displayName).toEqual(key)
        expect(lookupToolRenderer(key, true).displayName).toEqual(displayName)
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
        expect(lookupToolRenderer(key, false).displayName).toEqual(displayName)
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
        expect(lookupToolRenderer(key, false).displayName).toEqual(displayName)
    })

    it('falls back to the wrench card (key as displayName) for an unmapped built-in-looking name', () => {
        expect(toolRegistry.lookup('NotARealTool')).toBeNull()
        expect(lookupToolRenderer('NotARealTool', false).displayName).toEqual('NotARealTool')
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
