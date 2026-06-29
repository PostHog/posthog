import { z } from 'zod'

import type { ToolBase, ZodObjectAny } from './types'

/**
 * Optional per-call project override.
 *
 * Lets an agent target a single tool call at a different project than the
 * session's active one, without `switch-project` — which mutates the sticky
 * active project for the rest of the session and is the wrong tool for a one-off
 * (e.g. comparing the same insight across two projects, or a quick look at prod
 * mid-task). Resolution precedence in `StateManager.getProjectId()` is:
 * this arg > header/query pin > cached active project > `users/@me` default.
 *
 * The override is transient — scoped to the one handler invocation and never
 * written to the cache — so it cannot drift the active project. An out-of-scope
 * id needs no check here: the backend rejects `/api/projects/<id>/` with a 403
 * when the API key lacks the team.
 */
export const PROJECT_ID_OVERRIDE_PARAM = 'projectId' as const

const PROJECT_ID_OVERRIDE_DESCRIPTION =
    'Override the active project for this single call only. Does not change the active project — ' +
    'use switch-project for a persistent change. Defaults to the active project when omitted. ' +
    'Must be a project the API key can access, or the call returns a permission error.'

// Tools that must NOT receive the injected override:
//  - context-switch tools set the *persistent* active project/org,
//  - tools that already declare their own project id would get a colliding param,
//  - organization-scoped tools aren't project-nested, so an override is meaningless.
// Every other tool resolves its project through `getProjectId()`, so the override
// applies uniformly. This is a small, deliberate denylist rather than a per-tool
// opt-in so new project-scoped tools get the override for free.
const EXCLUDED_TOOLS = new Set<string>([
    'switch-project',
    'switch-organization',
    'get-llm-total-costs-for-project',
    'organizations-list',
    'organization-get',
    'projects-get',
])

const projectIdOverrideField = z.number().int().positive().optional().describe(PROJECT_ID_OVERRIDE_DESCRIPTION)

/**
 * Whether a tool is eligible for the injected override. The dispatcher must gate
 * `popProjectIdOverride` on this so it never strips an excluded tool's *own*
 * `projectId` arg (switch-project / get-llm-total-costs-for-project consume one).
 */
export function isProjectIdOverrideEligible(name: string): boolean {
    return !EXCLUDED_TOOLS.has(name)
}

/**
 * Extend a tool's input schema with the optional `projectId` override, unless the
 * tool is excluded or its schema isn't a plain object (top-level unions can't be
 * extended — those tools simply don't get the override). Single source: both
 * tools-mode (`tools/list` + `callTool`) and exec (`info`/`schema` + inner
 * dispatch) introspect and validate this same `base.schema`, so extending here
 * advertises and accepts the field in both modes at once.
 */
export function withProjectIdOverride(name: string, base: ToolBase<ZodObjectAny>): ToolBase<ZodObjectAny> {
    const schema = base.schema
    if (!isProjectIdOverrideEligible(name) || !(schema instanceof z.ZodObject)) {
        return base
    }
    return {
        ...base,
        schema: schema.extend({ [PROJECT_ID_OVERRIDE_PARAM]: projectIdOverrideField }),
    }
}

/**
 * Pull the override out of an already-validated input object and remove it in
 * place, so it never reaches the tool handler (handlers don't expect it, and it
 * must not leak into request bodies). Returns the id as a string for
 * `getProjectId`, or undefined when the caller didn't set it.
 */
export function popProjectIdOverride(input: Record<string, unknown>): string | undefined {
    const value = input[PROJECT_ID_OVERRIDE_PARAM]
    if (value === undefined) {
        return undefined
    }
    delete input[PROJECT_ID_OVERRIDE_PARAM]
    if (typeof value === 'number') {
        return String(value)
    }
    return typeof value === 'string' ? value : undefined
}
