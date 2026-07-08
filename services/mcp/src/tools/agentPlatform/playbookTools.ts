import { hasScope } from '@/lib/api'
import { getToolDefinitions, type ToolDefinitions } from '@/tools/toolDefinitions'

import type { PlaybookId } from './playbookIds'

// Representative MCP tools for executing each playbook. Curated (not derived from
// the per-tool description pointers, which map each tool to a single playbook —
// here a tool can legitimately appear under several). Only playbooks with tools
// are listed; the rest default to []. A vitest drift guard asserts every name
// resolves to a real tool definition; names absent from the running surface are
// skipped silently at render time.
export const PLAYBOOK_TOOLS: Partial<Record<PlaybookId, readonly string[]>> = {
    'reading-an-agent': [
        'agent-applications-list',
        'agent-applications-retrieve',
        'agent-applications-revisions-list',
        'agent-applications-revisions-retrieve',
        'agent-applications-revisions-manifest-retrieve',
        'agent-applications-revisions-bundle-retrieve',
        'agent-applications-revisions-system-prompt',
        'agent-applications-sessions-list',
        'agent-applications-sessions-retrieve',
    ],
    'debugging-sessions': [
        'agent-applications-sessions-list',
        'agent-applications-sessions-retrieve',
        'agent-applications-revisions-system-prompt',
        'agent-applications-revisions-cron-fire-create',
    ],
    'editing-agents-safely': [
        'agent-applications-revisions-new-draft-create',
        'agent-applications-revisions-clone-from-create',
        'agent-applications-revisions-agent-md-update',
        'agent-applications-revisions-spec-update',
        'agent-applications-revisions-skill-refs-update',
        'agent-applications-revisions-tools-update',
        'agent-applications-revisions-tools-destroy',
        'agent-applications-revisions-bundle-update',
        'agent-applications-revisions-partial-update',
        'agent-applications-revisions-validate-create',
        'agent-applications-revisions-freeze-create',
        'agent-applications-revisions-promote-create',
        'agent-applications-revisions-archive-create',
    ],
    'authoring-new-agents': [
        'agent-applications-create',
        'agent-native-tools-list',
        // The no-source first-revision creator — the one agents keep failing to find.
        'agent-applications-revisions-create',
        'agent-applications-revisions-partial-update',
        'agent-applications-revisions-bundle-update',
        'agent-applications-revisions-validate-create',
        'agent-applications-revisions-freeze-create',
        'agent-applications-revisions-promote-create',
    ],
    'secrets-and-integrations': [
        'agent-applications-env-keys-list',
        'agent-applications-env-keys-get',
        'agent-applications-env-keys-clear',
    ],
    'designing-mcp-surfaces': ['agent-native-tools-list'],
}

export interface PlaybookToolRef {
    name: string
    title: string
    requiredScopes: string[]
    /** Required scopes the caller's credential is missing. Empty = callable now. */
    missingScopes: string[]
}

/**
 * Resolve a playbook's representative tools against the live catalog + the caller's
 * scopes. Tools not present in the running surface are dropped (the catalog is the
 * ground truth — this is exactly what stops agents guessing a tool doesn't exist).
 *
 * `defs` defaults to the live catalog; it's a parameter so the drop-absent
 * behaviour can be exercised against a partial catalog in tests.
 */
export function buildToolSurface(
    playbookId: PlaybookId,
    scopes: string[],
    defs: ToolDefinitions = getToolDefinitions()
): PlaybookToolRef[] {
    const refs: PlaybookToolRef[] = []
    for (const name of PLAYBOOK_TOOLS[playbookId] ?? []) {
        const def = defs[name]
        if (!def) {
            continue
        }
        const requiredScopes = def.required_scopes ?? []
        const missingScopes = requiredScopes.filter((scope) => !hasScope(scopes, scope))
        refs.push({ name, title: def.title, requiredScopes, missingScopes })
    }
    return refs
}

/**
 * Render the tool surface as a markdown appendix. When `scopesKnown` is true the
 * tools are split into callable-now vs scope-gated (with the missing scope named);
 * otherwise they're listed flat with their required scopes.
 */
export function renderToolSurface(refs: PlaybookToolRef[], scopesKnown: boolean): string {
    if (refs.length === 0) {
        return ''
    }
    if (!scopesKnown) {
        const lines = ['## Tools for this playbook', '']
        for (const ref of refs) {
            const scopeNote = ref.requiredScopes.length ? ` (requires: ${ref.requiredScopes.join(', ')})` : ''
            lines.push(`- \`${ref.name}\` — ${ref.title}${scopeNote}`)
        }
        return lines.join('\n')
    }

    const callable = refs.filter((r) => r.missingScopes.length === 0)
    const gated = refs.filter((r) => r.missingScopes.length > 0)
    const lines = ['## Tools for this playbook (live)', '']
    if (callable.length) {
        lines.push('Callable with your current credential:')
        for (const ref of callable) {
            lines.push(`- \`${ref.name}\` — ${ref.title}`)
        }
        lines.push('')
    }
    if (gated.length) {
        lines.push('Present but NOT callable with your credential — add the scope, do not work around:')
        for (const ref of gated) {
            lines.push(`- \`${ref.name}\` — ${ref.title} (needs: ${ref.missingScopes.join(', ')})`)
        }
        lines.push('')
    }
    return lines.join('\n').trimEnd()
}
