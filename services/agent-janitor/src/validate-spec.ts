/**
 * Pre-flight validation for a draft / ready revision.
 *
 * Catches the shape problems that would otherwise surface as a session-start
 * crash on first invoke: missing entrypoint, unknown native tool ids, custom
 * tools without a compiled.js, skills that point at files that aren't in the
 * bundle.
 *
 * Spec parsing itself is guaranteed by the revision store (PgRevisionStore
 * runs `AgentSpecSchema.parse(row.spec ?? {})` on every read), so we don't
 * re-validate the spec shape here.
 *
 * Secrets validation lives in Django — it owns the encrypted env block and
 * the Fernet keys. The janitor only validates bundle-side things.
 */

import { AgentRevision, BundleStore } from '@posthog/agent-shared'
import { hasNativeTool } from '@posthog/agent-tools'

export type ValidationCode =
    | 'missing_entrypoint'
    | 'unknown_native_tool'
    | 'missing_custom_tool_compiled'
    | 'missing_custom_tool_schema'
    | 'missing_skill'

export interface ValidationError {
    code: ValidationCode
    message: string
    /** Spec path the error attaches to (e.g. "spec.tools[2].id", "spec.entrypoint"). */
    pointer: string
}

export interface ValidationReport {
    ok: boolean
    revision_id: string
    revision_state: AgentRevision['state']
    errors: ValidationError[]
    /** Native tool ids referenced by the spec that resolved fine. */
    resolved_natives: string[]
}

export async function validateRevisionBundle(rev: AgentRevision, bundle: BundleStore): Promise<ValidationReport> {
    const errors: ValidationError[] = []
    const resolvedNatives: string[] = []

    const entrypoint = rev.spec.entrypoint || 'agent.md'
    if (!(await bundle.exists(rev.id, entrypoint))) {
        errors.push({
            code: 'missing_entrypoint',
            message: `entrypoint "${entrypoint}" is not present in the bundle`,
            pointer: 'spec.entrypoint',
        })
    }

    for (const [i, tool] of rev.spec.tools.entries()) {
        if (tool.kind === 'native') {
            if (!hasNativeTool(tool.id)) {
                errors.push({
                    code: 'unknown_native_tool',
                    message: `native tool "${tool.id}" is not registered in @posthog/agent-tools`,
                    pointer: `spec.tools[${i}].id`,
                })
            } else {
                resolvedNatives.push(tool.id)
            }
            continue
        }
        const base = tool.path.replace(/\/$/, '')
        const compiled = `${base}/compiled.js`
        const schema = `${base}/schema.json`
        if (!(await bundle.exists(rev.id, compiled))) {
            errors.push({
                code: 'missing_custom_tool_compiled',
                message: `custom tool "${tool.id}" is missing "${compiled}"`,
                pointer: `spec.tools[${i}].path`,
            })
        }
        if (!(await bundle.exists(rev.id, schema))) {
            errors.push({
                code: 'missing_custom_tool_schema',
                message: `custom tool "${tool.id}" is missing "${schema}"`,
                pointer: `spec.tools[${i}].path`,
            })
        }
    }

    for (const [i, skill] of rev.spec.skills.entries()) {
        if (!(await bundle.exists(rev.id, skill.path))) {
            errors.push({
                code: 'missing_skill',
                message: `skill "${skill.id}" path "${skill.path}" is not present in the bundle`,
                pointer: `spec.skills[${i}].path`,
            })
        }
    }

    return {
        ok: errors.length === 0,
        revision_id: rev.id,
        revision_state: rev.state,
        errors,
        resolved_natives: resolvedNatives,
    }
}
