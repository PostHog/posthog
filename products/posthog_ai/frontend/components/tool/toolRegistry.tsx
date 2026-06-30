import { type ComponentType, type LazyExoticComponent, lazy } from 'react'

import {
    IconAI,
    IconCommit,
    IconDocument,
    IconEye,
    IconGitBranch,
    IconGithub,
    IconGlobe,
    IconListCheck,
    IconMagicWand,
    IconPencil,
    IconSearch,
    IconTerminal,
    IconWrench,
} from '@posthog/icons'

// IconRobot is not exported from @posthog/icons — it lives only in the legacy lib icon set.
import { IconRobot } from 'lib/lemon-ui/icons'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

export interface ToolRendererProps {
    message: ToolCallMessage
    isLastInGroup: boolean
    /**
     * Resolved registry entry's icon — the registry's contribution to the card. Renderers use it for
     * the header icon (built-ins get their friendly icon instead of the generic wrench). Optional so
     * direct mounts default to the renderer's own fallback icon.
     */
    icon?: JSX.Element
    /** Resolved registry entry's stable display name, used as the header label when no title exists. */
    displayName?: string
    /** Turn-level signals so a still-incomplete tool reads as loading vs cancelled vs idle. */
    turnComplete?: boolean
    turnCancelled?: boolean
}

/** A renderer reachable eagerly or via a lazy chunk — both render identically in `ToolCallCard`. */
type ToolRendererComponent = ComponentType<ToolRendererProps> | LazyExoticComponent<ComponentType<ToolRendererProps>>

export interface ToolRegistryEntry {
    /**
     * Registry key. For single-exec PostHog tools, this is the **inner** tool name parsed from
     * `rawInput.command` (e.g. "execute-sql", "insight-create"); for `exec`'s discovery verbs,
     * the sentinel "__posthog_exec_tools__" etc.; for non-exec MCP tools and Claude built-ins,
     * the wire `toolName` directly (e.g. "TodoWrite", "WebSearch").
     */
    key: string
    /** Display name / icon for fallback rendering and for the tool-call header line. */
    displayName: string
    icon: JSX.Element
    Renderer: ToolRendererComponent
}

export interface ToolRegistry {
    register: (entry: ToolRegistryEntry) => void
    lookup: (toolName: string) => ToolRegistryEntry | null
}

class MapBackedRegistry implements ToolRegistry {
    private entries = new Map<string, ToolRegistryEntry>()

    register(entry: ToolRegistryEntry): void {
        this.entries.set(entry.key, entry)
    }

    lookup(toolName: string): ToolRegistryEntry | null {
        return this.entries.get(toolName) ?? null
    }
}

// Renderers are code-split: the static graph below carries only icons, types, and lazy factories, so a
// sandbox conversation pulls a renderer's chunk on first use, not at thread mount. The built-in tools
// and the generic MCP card share one chunk (`builtinToolRenderers`); each heavy data-tool adapter and
// the Monaco-backed diff renderer stay in their own chunks.
const BuiltinToolRenderer = lazy(() =>
    import('./builtinToolRenderers').then((m) => ({ default: m.BuiltinToolRenderer }))
)
const EditToolRenderer = lazy(() => import('./EditDiffRenderer').then((m) => ({ default: m.EditDiffRenderer })))
const QuestionRenderer = lazy(() => import('../QuestionRenderer').then((m) => ({ default: m.QuestionRenderer })))
const PostHogCodeToolRenderer = lazy(() =>
    import('./posthogCodeToolRenderers').then((m) => ({ default: m.PostHogCodeToolRenderer }))
)

/**
 * Single module-level registry of tool-name → renderer entry. All entries are registered at module
 * load — no dynamic registration, no hooks, no scene callbacks. Custom adapters are registered per
 * tool; any tool without one falls through to the built-in renderer's generic MCP card.
 */
export const toolRegistry: ToolRegistry = new MapBackedRegistry()

/**
 * Bulk-register tool renderers into the shared registry. The generic per-product seam: a product
 * registers its tool cards from its own scene's entrypoint (as Max does via `registerMaxToolRenderers`).
 * `toolRegistry.register` stays available for single-entry use.
 */
export function registerToolRenderers(entries: ToolRegistryEntry[]): void {
    for (const entry of entries) {
        toolRegistry.register(entry)
    }
}

// Product-specific data-tool renderers (insight, dashboard, session recordings, error tracking,
// notebooks, query wrappers) are NOT registered here — they live in scenes/max and register themselves
// into this registry via `registerMaxToolRenderers` so this surface stays free of any scenes/max import.
// Surfaces without those adapters (tasks, signals inbox) fall through to the generic MCP card.

// --- Claude built-in tools ---
// Keyed by the stable SDK tool name (reachable via `_meta.claudeCode.toolName`). Bash/Read/Search/Web
// get a dedicated per-tool card; the rest fall through to the generic MCP card — all inside the single
// `BuiltinToolRenderer` chunk, which switches on the resolved tool name. The registry supplies the
// friendly icon + a stable `displayName` for frames whose `title` is empty. `Skill` is registered
// speculatively (not enumerated in the agent's tools.ts) — zero cost if never emitted. File-editing
// built-ins are split out below into the dedicated diff renderer.
const BUILTIN_TOOLS: { keys: string[]; displayName: string; icon: JSX.Element }[] = [
    { keys: ['Read', 'NotebookRead'], displayName: 'Read', icon: <IconEye /> },
    { keys: ['Grep', 'Glob', 'LS'], displayName: 'Search', icon: <IconSearch /> },
    { keys: ['Bash', 'BashOutput', 'KillShell'], displayName: 'Terminal', icon: <IconTerminal /> },
    { keys: ['WebSearch', 'WebFetch'], displayName: 'Web', icon: <IconGlobe /> },
    { keys: ['Task', 'Agent'], displayName: 'Subagent', icon: <IconRobot /> },
    {
        keys: ['TaskCreate', 'TaskUpdate', 'TaskGet', 'TaskList', 'TodoWrite'],
        displayName: 'Tasks',
        icon: <IconListCheck />,
    },
    { keys: ['Skill'], displayName: 'Skill', icon: <IconMagicWand /> },
    { keys: ['ToolSearch'], displayName: 'Tool search', icon: <IconSearch /> },
    { keys: ['ExitPlanMode'], displayName: 'Plan', icon: <IconDocument /> },
]
for (const { keys, displayName, icon } of BUILTIN_TOOLS) {
    for (const key of keys) {
        toolRegistry.register({ key, displayName, icon, Renderer: BuiltinToolRenderer })
    }
}

// File-editing built-ins render an inline visual diff when the agent attaches `type: "diff"` content
// blocks; EditDiffRenderer falls back to the generic card when none are present.
for (const key of ['Edit', 'Write', 'NotebookEdit', 'MultiEdit']) {
    toolRegistry.register({ key, displayName: 'Edit', icon: <IconPencil />, Renderer: EditToolRenderer })
}

// PostHog single-exec discovery verbs. `resolveToolKey` parses `exec tools|search|info|schema` into
// these sentinel keys; PostHogExecRenderer (inside the built-in chunk) derives the friendly label and
// input preview from the command. Registered so they get a fitting icon instead of the wrench fallback.
const POSTHOG_EXEC_VERBS: { key: string; displayName: string; icon: JSX.Element }[] = [
    { key: '__posthog_exec_tools__', displayName: 'List tools', icon: <IconListCheck /> },
    { key: '__posthog_exec_search__', displayName: 'Search tools', icon: <IconSearch /> },
    { key: '__posthog_exec_info__', displayName: 'Read tool', icon: <IconDocument /> },
    { key: '__posthog_exec_schema__', displayName: 'Inspect schema', icon: <IconDocument /> },
    { key: '__posthog_exec_unknown__', displayName: 'Run command', icon: <IconWrench /> },
]
for (const { key, displayName, icon } of POSTHOG_EXEC_VERBS) {
    toolRegistry.register({ key, displayName, icon, Renderer: BuiltinToolRenderer })
}

// posthog-code-tools — the coding agent's git/repo MCP tools. Registered under both the bare name and
// the `mcp__<server>__` qualified name because `resolveToolKey` yields the qualified form on the
// Claude-SDK wire path (the name lives in `_meta.claudeCode.toolName`) and the bare form on a native
// MCP path. Renderers live in their own lazy chunk.
// Inlined rather than imported from the renderer module so registration stays a string-only side
// effect — importing it would statically pull the lazy renderer chunk into this one.
const POSTHOG_CODE_TOOLS_SERVER = 'posthog-code-tools'
const POSTHOG_CODE_TOOLS: { name: string; displayName: string; icon: JSX.Element }[] = [
    { name: 'git_signed_commit', displayName: 'Signed commits', icon: <IconCommit /> },
    { name: 'git_signed_merge', displayName: 'Signed merge', icon: <IconGitBranch /> },
    { name: 'git_signed_rewrite', displayName: 'Signed force-update', icon: <IconGitBranch /> },
    { name: 'clone_repo', displayName: 'Clone repository', icon: <IconGithub /> },
    { name: 'list_repos', displayName: 'List repositories', icon: <IconGithub /> },
]
for (const { name, displayName, icon } of POSTHOG_CODE_TOOLS) {
    for (const key of [name, `mcp__${POSTHOG_CODE_TOOLS_SERVER}__${name}`]) {
        toolRegistry.register({ key, displayName, icon, Renderer: PostHogCodeToolRenderer })
    }
}

// AskUserQuestion (the agent asking the user to pick between options) gets a bespoke renderer that
// lays the question + options out like the LangGraph question recap, rather than the generic JSON card.
toolRegistry.register({
    key: 'AskUserQuestion',
    displayName: 'Question',
    icon: <IconAI />,
    Renderer: QuestionRenderer,
})

/** Looks up the renderer entry for a resolved tool key, falling back to the generic built-in card. */
export function lookupToolRenderer(resolvedKey: string): ToolRegistryEntry {
    return (
        toolRegistry.lookup(resolvedKey) ?? {
            key: resolvedKey,
            displayName: resolvedKey,
            icon: <IconWrench />,
            Renderer: BuiltinToolRenderer,
        }
    )
}
