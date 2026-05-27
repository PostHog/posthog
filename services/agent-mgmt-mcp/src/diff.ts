/**
 * Two-layer diff between revisions: structural (spec JSONB) and content (bundle
 * files). Used by both the wizard ("show me what I'm about to change") and the
 * power-user UI side-by-side view.
 */

import { AgentSpec, BundleEntry, BundleStore } from '@posthog/agent-shared-v2'

export interface SpecDiff {
    model: { before: string; after: string } | null
    tools: { added: string[]; removed: string[]; modified: string[] }
    triggers: { added: number; removed: number }
    mcps: { added: number; removed: number }
    skills: { added: string[]; removed: string[] }
    integrations: { added: string[]; removed: string[] }
    secrets: { added: string[]; removed: string[] }
    limits: Partial<Record<keyof AgentSpec['limits'], { before: number; after: number }>>
}

export interface FileDiff {
    path: string
    kind: 'added' | 'removed' | 'modified' | 'unchanged'
    sizeBefore?: number
    sizeAfter?: number
}

export interface RevisionDiff {
    spec: SpecDiff
    files: FileDiff[]
}

export function diffSpec(before: AgentSpec, after: AgentSpec): SpecDiff {
    const beforeToolIds = before.tools.map((t) => t.id)
    const afterToolIds = after.tools.map((t) => t.id)
    return {
        model: before.model === after.model ? null : { before: before.model, after: after.model },
        tools: {
            added: afterToolIds.filter((id) => !beforeToolIds.includes(id)),
            removed: beforeToolIds.filter((id) => !afterToolIds.includes(id)),
            modified: afterToolIds.filter((id) => {
                const a = before.tools.find((t) => t.id === id)
                const b = after.tools.find((t) => t.id === id)
                return !!a && !!b && a.kind !== b.kind
            }),
        },
        triggers: {
            added:
                after.triggers.length - before.triggers.length > 0 ? after.triggers.length - before.triggers.length : 0,
            removed:
                before.triggers.length - after.triggers.length > 0 ? before.triggers.length - after.triggers.length : 0,
        },
        mcps: {
            added: Math.max(0, after.mcps.length - before.mcps.length),
            removed: Math.max(0, before.mcps.length - after.mcps.length),
        },
        skills: {
            added: after.skills.map((s) => s.id).filter((id) => !before.skills.find((b) => b.id === id)),
            removed: before.skills.map((s) => s.id).filter((id) => !after.skills.find((a) => a.id === id)),
        },
        integrations: {
            added: after.integrations.filter((i) => !before.integrations.includes(i)),
            removed: before.integrations.filter((i) => !after.integrations.includes(i)),
        },
        secrets: {
            added: after.secrets.filter((s) => !before.secrets.includes(s)),
            removed: before.secrets.filter((s) => !after.secrets.includes(s)),
        },
        limits: diffLimits(before.limits, after.limits),
    }
}

function diffLimits(before: AgentSpec['limits'], after: AgentSpec['limits']): SpecDiff['limits'] {
    const out: SpecDiff['limits'] = {}
    for (const key of Object.keys(after) as Array<keyof AgentSpec['limits']>) {
        if (before[key] !== after[key]) {
            out[key] = { before: before[key], after: after[key] }
        }
    }
    return out
}

export async function diffFiles(bundle: BundleStore, beforeRev: string, afterRev: string): Promise<FileDiff[]> {
    const before = await bundle.list(beforeRev)
    const after = await bundle.list(afterRev)
    const beforeMap = new Map<string, BundleEntry>(before.map((e) => [e.path, e]))
    const afterMap = new Map<string, BundleEntry>(after.map((e) => [e.path, e]))
    const allPaths = new Set([...beforeMap.keys(), ...afterMap.keys()])
    const diffs: FileDiff[] = []
    for (const path of allPaths) {
        const b = beforeMap.get(path)
        const a = afterMap.get(path)
        if (b && !a) {
            diffs.push({ path, kind: 'removed', sizeBefore: b.size })
        } else if (!b && a) {
            diffs.push({ path, kind: 'added', sizeAfter: a.size })
        } else if (b && a) {
            diffs.push({
                path,
                kind: b.sha256 === a.sha256 ? 'unchanged' : 'modified',
                sizeBefore: b.size,
                sizeAfter: a.size,
            })
        }
    }
    diffs.sort((x, y) => x.path.localeCompare(y.path))
    return diffs
}
