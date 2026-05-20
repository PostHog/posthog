/**
 * `notebooks-collab-edit` tool.
 *
 * Applies an apply_patch-style diff to a notebook by:
 *   1. GET /notebooks/{short_id} → current `content` + `version`.
 *   2. Build a permissive ProseMirror schema from the doc.
 *   3. Parse the patch → array of hunks.
 *   4. For each hunk, compute a `ReplaceStep` against the doc; accumulate
 *      steps and the resulting doc.
 *   5. POST /notebooks/{short_id}/collab/save/ with `steps`, `content`,
 *      `version`. The server's Redis-streaming endpoint broadcasts each
 *      step to other connected clients so the edit appears live in
 *      open notebooks.
 *   6. On 409, rebase pending steps over the missed steps the server
 *      returned in the body, then POST again. Capped retries.
 *   7. On 410, return a structured error telling the agent to refetch.
 *
 * Why a separate tool from `notebooks-partial-update`:
 *   - `notebooks-partial-update` calls the legacy PATCH path which writes
 *     `content` directly without streaming to other clients. Edits made
 *     through it are invisible to anyone with the notebook open until they
 *     reload — bad UX for human-agent collaboration.
 *   - `collab/save` is the new streaming path. Other clients receive each
 *     step over SSE in near-real-time.
 */
import { Node as PMNode, type Schema } from 'prosemirror-model'
import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { AnalyticsEvent } from '@/lib/analytics'
import type { Context, ToolBase } from '@/tools/types'

import { type BuildError, buildSteps } from './buildSteps'
import { type ParsedPatch, PatchParseError, parsePatch } from './patch'
import type { RebaseErr } from './rebase'
import { saveStepsWithRebase } from './saveLoop'
import { buildSchemaForDoc, packDocAttrs } from './schema'

export const NotebooksCollabEditSchema = z.object({
    short_id: z.string().describe('The notebook short_id (visible in the URL, e.g. `aBcD1234`).'),
    patch: z.string().describe(
        // Spelt out so the agent knows precisely what shape we accept. Mirrors
        // the apply_patch convention from OpenAI's cookbook, simplified to a
        // single document target.
        'apply_patch-style diff against the notebook. ' +
            'Each line of the rendered notebook corresponds to one top-level block (paragraph, heading, list item, etc.). ' +
            'Format:\n' +
            '```\n' +
            '*** Begin Patch\n' +
            '@@\n' +
            ' context line (existing block, unchanged)\n' +
            '-block to remove\n' +
            '+block to add (will be inserted as a paragraph)\n' +
            '*** End Patch\n' +
            '```\n' +
            'Rules: every line must start with " " (context), "-" (remove) or "+" (add). ' +
            'Multiple hunks (each starting with `@@`) are applied in order. ' +
            'Context lines must match the existing notebook content exactly — call `notebooks-retrieve` first to see what to anchor against. ' +
            'Atomic block widgets (lines like `<atom:ph-recording>`) can be kept as context or removed, but cannot be added via "+" — they require dedicated insertion flows.'
    ),
    title: z.string().optional().describe('Optional new title for the notebook. Omit to leave the title unchanged.'),
})

type Params = z.infer<typeof NotebooksCollabEditSchema>

function formatBuildError(error: BuildError): { ok: false; isError: true; error: BuildError } {
    return { ok: false, isError: true, error }
}

function formatPatchParseError(error: PatchParseError): {
    ok: false
    isError: true
    error: { code: 'patch_parse_error'; message: string; line_number: number }
} {
    return {
        ok: false,
        isError: true,
        error: {
            code: 'patch_parse_error',
            message:
                `Could not parse the patch: ${error.message}. ` +
                'Each hunk must start with `@@` and every line within a hunk must start with " " (context), "-" (remove), or "+" (add). ' +
                'See the tool description for the exact format.',
            line_number: error.lineNumber,
        },
    }
}

export type CollabEditResult =
    | {
          ok: true
          isError?: false
          notebook: Schemas.Notebook
          steps_applied: number
          rebases: number
      }
    | {
          ok: false
          isError: true
          error:
              | BuildError
              | RebaseErr
              | { code: 'patch_parse_error'; message: string; line_number: number }
              | { code: 'stale_buffer'; message: string }
              | { code: 'rebase_exhausted'; attempts: number; message: string }
      }

export const collabEditHandler: ToolBase<typeof NotebooksCollabEditSchema, CollabEditResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    // 1. Fetch current notebook.
    const notebook = await context.api.request<Schemas.Notebook>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/${encodeURIComponent(params.short_id)}/`,
    })

    if (notebook.content === undefined || notebook.content === null || typeof notebook.content !== 'object') {
        throw new Error(
            `Notebook ${params.short_id} has no editable content (got ${typeof notebook.content}). ` +
                'Create the notebook with `notebooks-create` first, or use `notebooks-partial-update` to set initial content.'
        )
    }

    // 2. Parse patch.
    let patch: ParsedPatch
    try {
        patch = parsePatch(params.patch)
    } catch (e) {
        if (e instanceof PatchParseError) {
            return formatPatchParseError(e)
        }
        throw e
    }

    // 3. Build schema + parse doc.
    const rawContent = notebook.content as Record<string, unknown>
    const packed = packDocAttrs(rawContent as unknown as Parameters<typeof packDocAttrs>[0])
    const schema: Schema = buildSchemaForDoc(rawContent as unknown as Parameters<typeof buildSchemaForDoc>[0])
    let doc: PMNode
    try {
        doc = PMNode.fromJSON(schema, packed as unknown as Parameters<typeof PMNode.fromJSON>[1])
    } catch (e) {
        throw new Error(
            `Failed to parse notebook content into a ProseMirror document: ${e instanceof Error ? e.message : String(e)}. ` +
                'This is usually a schema-incompatibility bug in the MCP — please report it. As a fallback, use `notebooks-partial-update` to replace the content wholesale.'
        )
    }

    // 4. Build steps.
    const built = buildSteps(doc, patch, schema)
    if (!built.ok) {
        return formatBuildError(built.error)
    }

    if (built.steps.length === 0) {
        // The patch was a no-op (every line was context). Return current notebook
        // without round-tripping through the server so the agent gets a clear
        // signal that nothing changed.
        return {
            ok: true,
            notebook,
            steps_applied: 0,
            rebases: 0,
        }
    }

    if (typeof notebook.version !== 'number') {
        throw new Error(
            `Notebook ${params.short_id} has no numeric version (got ${typeof notebook.version}). ` +
                'The collab/save endpoint requires optimistic concurrency control — refetch the notebook and retry.'
        )
    }

    // 5. POST with rebase retry loop.
    const result = await saveStepsWithRebase({
        context,
        projectId,
        shortId: params.short_id,
        clientId: uuidv4(),
        oldDoc: doc,
        schema,
        pendingSteps: built.steps,
        newDoc: built.newDoc,
        version: notebook.version,
        title: params.title,
    })

    if (!result.ok) {
        return { ok: false, isError: true, error: result.error }
    }

    void context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
        tool: 'notebooks-collab-edit',
        steps_count: result.steps_applied,
        rebases: result.rebases,
        hunks: patch.hunks.length,
    })

    return {
        ok: true,
        notebook: result.notebook,
        steps_applied: result.steps_applied,
        rebases: result.rebases,
    }
}

const tool = (): ToolBase<typeof NotebooksCollabEditSchema, CollabEditResult> => ({
    name: 'notebooks-collab-edit',
    schema: NotebooksCollabEditSchema,
    handler: collabEditHandler,
})

export default tool
