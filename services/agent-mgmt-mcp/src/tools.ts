/**
 * agent_mgmt:* MCP namespace.
 *
 * These are boring CRUD primitives — the smarts live in the authoring guide
 * (see resources.ts). Authors drive these via an MCP client. Each tool's
 * `handler` is independent of the MCP framework — they take typed params and
 * return typed results. The bridge to services/mcp registers them as
 * MCP tools by wrapping the handlers; that wiring lives separately.
 */

import { z } from 'zod'

import { AgentSpec, AgentSpecSchema, BundleStore, RevisionStore } from '@posthog/agent-shared-v2'
import { listNativeTools } from '@posthog/agent-tools'

import { Compiler } from './compile'
import { diffFiles, diffSpec, RevisionDiff } from './diff'

export interface AgentMgmtDeps {
    revisions: RevisionStore
    bundle: BundleStore
    compiler: Compiler
    teamId: number
    userId: string
}

/* -------------------------------------------------------------------------- */
/* Agents                                                                     */
/* -------------------------------------------------------------------------- */

export async function listAgents(
    deps: AgentMgmtDeps
): Promise<Array<{ slug: string; name: string; live_revision_id: string | null }>> {
    const apps = await deps.revisions.listApplications(deps.teamId)
    return apps.map((a) => ({ slug: a.slug, name: a.name, live_revision_id: a.live_revision_id }))
}

export const GetAgentSchema = z.object({ slug: z.string() })
export async function getAgent(
    deps: AgentMgmtDeps,
    args: z.infer<typeof GetAgentSchema>
): Promise<{
    application: { slug: string; name: string; live_revision_id: string | null }
    revisions: Array<{ id: string; state: string; created_at: string }>
}> {
    const app = await deps.revisions.getApplicationBySlug(deps.teamId, args.slug)
    if (!app) {
        throw new Error(`agent not found: ${args.slug}`)
    }
    const revs = await deps.revisions.listRevisions(app.id)
    return {
        application: { slug: app.slug, name: app.name, live_revision_id: app.live_revision_id },
        revisions: revs.map((r) => ({ id: r.id, state: r.state, created_at: r.created_at })),
    }
}

export const GetRevisionSchema = z.object({ rev_id: z.string() })
export async function getRevision(
    deps: AgentMgmtDeps,
    args: z.infer<typeof GetRevisionSchema>
): Promise<{
    revision: { id: string; state: string; spec: AgentSpec; bundle_sha256: string | null }
    files: Array<{ path: string; size: number; sha256: string }>
}> {
    const r = await deps.revisions.getRevision(args.rev_id)
    if (!r) {
        throw new Error(`revision not found: ${args.rev_id}`)
    }
    const files = await deps.bundle.list(r.id)
    return {
        revision: { id: r.id, state: r.state, spec: r.spec, bundle_sha256: r.bundle_sha256 },
        files,
    }
}

export const DiffRevisionsSchema = z.object({ a: z.string(), b: z.string() })
export async function diffRevisions(
    deps: AgentMgmtDeps,
    args: z.infer<typeof DiffRevisionsSchema>
): Promise<RevisionDiff> {
    const a = await deps.revisions.getRevision(args.a)
    const b = await deps.revisions.getRevision(args.b)
    if (!a || !b) {
        throw new Error('both revisions must exist')
    }
    return {
        spec: diffSpec(a.spec, b.spec),
        files: await diffFiles(deps.bundle, a.id, b.id),
    }
}

export const CreateRevisionSchema = z.object({
    slug: z.string(),
    parent_revision_id: z.string().nullable().optional(),
    name: z.string().optional(),
    description: z.string().optional(),
})
export async function createRevision(
    deps: AgentMgmtDeps,
    args: z.infer<typeof CreateRevisionSchema>
): Promise<{
    application_id: string
    revision_id: string
}> {
    let app = await deps.revisions.getApplicationBySlug(deps.teamId, args.slug)
    if (!app) {
        app = await deps.revisions.createApplication({
            team_id: deps.teamId,
            slug: args.slug,
            name: args.name ?? args.slug,
            description: args.description ?? '',
        })
    }
    let parentSpec: AgentSpec = AgentSpecSchema.parse({ model: 'claude-opus-4-7' })
    if (args.parent_revision_id) {
        const parent = await deps.revisions.getRevision(args.parent_revision_id)
        if (parent) {
            parentSpec = parent.spec
        }
    }
    const rev = await deps.revisions.createRevision({
        application_id: app.id,
        parent_revision_id: args.parent_revision_id ?? null,
        created_by: deps.userId,
        bundle_uri: `s3://agents/${app.id}/`,
        spec: parentSpec,
    })
    if (args.parent_revision_id) {
        const parentFiles = await deps.bundle.list(args.parent_revision_id)
        for (const f of parentFiles) {
            await deps.bundle.copy(args.parent_revision_id, f.path, rev.id, f.path)
        }
    } else {
        await deps.bundle.write(rev.id, 'agent.md', '# Agent\n\nDescribe what this agent does.\n')
    }
    return { application_id: app.id, revision_id: rev.id }
}

export const PromoteRevisionSchema = z.object({ rev_id: z.string() })
export async function promoteRevision(
    deps: AgentMgmtDeps,
    args: z.infer<typeof PromoteRevisionSchema>
): Promise<{
    rev_id: string
    bundle_sha256: string
}> {
    const sha = await deps.bundle.freeze(args.rev_id)
    await deps.revisions.setRevisionState(args.rev_id, 'ready', sha)
    return { rev_id: args.rev_id, bundle_sha256: sha }
}

export const DeployRevisionSchema = z.object({ rev_id: z.string() })
export async function deployRevision(
    deps: AgentMgmtDeps,
    args: z.infer<typeof DeployRevisionSchema>
): Promise<{ ok: true }> {
    const rev = await deps.revisions.getRevision(args.rev_id)
    if (!rev) {
        throw new Error(`revision not found: ${args.rev_id}`)
    }
    if (rev.state === 'draft') {
        throw new Error('revision must be promoted (ready) before deploy')
    }
    await deps.revisions.setRevisionState(args.rev_id, 'live')
    await deps.revisions.setLiveRevision(rev.application_id, args.rev_id)
    return { ok: true }
}

export const ArchiveAgentSchema = z.object({ slug: z.string() })
export async function archiveAgent(
    deps: AgentMgmtDeps,
    args: z.infer<typeof ArchiveAgentSchema>
): Promise<{ ok: true }> {
    const app = await deps.revisions.getApplicationBySlug(deps.teamId, args.slug)
    if (!app) {
        throw new Error(`agent not found: ${args.slug}`)
    }
    await deps.revisions.archiveApplication(app.id)
    return { ok: true }
}

/* -------------------------------------------------------------------------- */
/* Spec edits (DB layer)                                                      */
/* -------------------------------------------------------------------------- */

export const UpdateSpecSchema = z.object({
    rev_id: z.string(),
    /** Partial — merged into existing spec, then re-validated. */
    spec_patch: z.record(z.string(), z.unknown()),
})
export async function updateSpec(
    deps: AgentMgmtDeps,
    args: z.infer<typeof UpdateSpecSchema>
): Promise<{ spec: AgentSpec }> {
    const rev = await deps.revisions.getRevision(args.rev_id)
    if (!rev) {
        throw new Error(`revision not found: ${args.rev_id}`)
    }
    const merged = { ...rev.spec, ...args.spec_patch }
    const validated = AgentSpecSchema.parse(merged)
    await deps.revisions.updateSpec(args.rev_id, validated)
    return { spec: validated }
}

/* -------------------------------------------------------------------------- */
/* File operations (S3 bundle layer)                                          */
/* -------------------------------------------------------------------------- */

export const ListFilesSchema = z.object({ rev_id: z.string(), prefix: z.string().optional() })
export async function listFiles(
    deps: AgentMgmtDeps,
    args: z.infer<typeof ListFilesSchema>
): Promise<{
    files: Array<{ path: string; size: number; sha256: string }>
}> {
    const files = await deps.bundle.list(args.rev_id, args.prefix)
    return { files }
}

export const ReadFileSchema = z.object({ rev_id: z.string(), path: z.string() })
export async function readFile(
    deps: AgentMgmtDeps,
    args: z.infer<typeof ReadFileSchema>
): Promise<{ content: string }> {
    return { content: await deps.bundle.readText(args.rev_id, args.path) }
}

export const WriteFileSchema = z.object({ rev_id: z.string(), path: z.string(), content: z.string() })
export async function writeFile(
    deps: AgentMgmtDeps,
    args: z.infer<typeof WriteFileSchema>
): Promise<{
    path: string
    sha256: string
    compiled?: { schema_json_path: string }
}> {
    await deps.bundle.write(args.rev_id, args.path, args.content)
    // Auto-compile TS tool source
    const toolMatch = /^tools\/([^/]+)\/source\.ts$/.exec(args.path)
    if (toolMatch) {
        const toolId = toolMatch[1]
        const compiled = await deps.compiler.compile(args.content, toolId)
        await deps.bundle.write(args.rev_id, `tools/${toolId}/compiled.js`, compiled.compiledJs)
        await deps.bundle.write(
            args.rev_id,
            `tools/${toolId}/schema.json`,
            JSON.stringify(compiled.schemaJson, null, 2)
        )
        await deps.bundle.write(
            args.rev_id,
            `tools/${toolId}/inputs.json`,
            JSON.stringify(compiled.inputsJson, null, 2)
        )
        return {
            path: args.path,
            sha256: (await deps.bundle.list(args.rev_id, args.path)).find((f) => f.path === args.path)?.sha256 ?? '',
            compiled: { schema_json_path: `tools/${toolId}/schema.json` },
        }
    }
    const entries = await deps.bundle.list(args.rev_id, args.path)
    const exact = entries.find((e) => e.path === args.path)
    return { path: args.path, sha256: exact?.sha256 ?? '' }
}

export const DeleteFileSchema = z.object({ rev_id: z.string(), path: z.string() })
export async function deleteFile(deps: AgentMgmtDeps, args: z.infer<typeof DeleteFileSchema>): Promise<{ ok: true }> {
    await deps.bundle.delete(args.rev_id, args.path)
    return { ok: true }
}

export const CopyFileSchema = z.object({
    src_rev_id: z.string(),
    src_path: z.string(),
    dst_rev_id: z.string(),
    dst_path: z.string(),
})
export async function copyFile(deps: AgentMgmtDeps, args: z.infer<typeof CopyFileSchema>): Promise<{ ok: true }> {
    await deps.bundle.copy(args.src_rev_id, args.src_path, args.dst_rev_id, args.dst_path)
    return { ok: true }
}

/* -------------------------------------------------------------------------- */
/* Catalog                                                                    */
/* -------------------------------------------------------------------------- */

export async function listAvailableTools(_deps: AgentMgmtDeps): Promise<{
    native: Array<{ id: string; description: string; cost_hint: string }>
}> {
    return {
        native: listNativeTools().map((t) => ({
            id: t.id,
            description: t.schema.description,
            cost_hint: t.schema.cost_hint,
        })),
    }
}

/* -------------------------------------------------------------------------- */
/* Registry — single map for MCP wiring                                       */
/* -------------------------------------------------------------------------- */

export const AGENT_MGMT_HANDLERS = {
    'agent_mgmt.list_agents': { schema: z.object({}), handler: (deps: AgentMgmtDeps) => listAgents(deps) },
    'agent_mgmt.get_agent': { schema: GetAgentSchema, handler: getAgent },
    'agent_mgmt.get_revision': { schema: GetRevisionSchema, handler: getRevision },
    'agent_mgmt.diff_revisions': { schema: DiffRevisionsSchema, handler: diffRevisions },
    'agent_mgmt.create_revision': { schema: CreateRevisionSchema, handler: createRevision },
    'agent_mgmt.promote_revision': { schema: PromoteRevisionSchema, handler: promoteRevision },
    'agent_mgmt.deploy_revision': { schema: DeployRevisionSchema, handler: deployRevision },
    'agent_mgmt.archive_agent': { schema: ArchiveAgentSchema, handler: archiveAgent },
    'agent_mgmt.update_spec': { schema: UpdateSpecSchema, handler: updateSpec },
    'agent_mgmt.list_files': { schema: ListFilesSchema, handler: listFiles },
    'agent_mgmt.read_file': { schema: ReadFileSchema, handler: readFile },
    'agent_mgmt.write_file': { schema: WriteFileSchema, handler: writeFile },
    'agent_mgmt.delete_file': { schema: DeleteFileSchema, handler: deleteFile },
    'agent_mgmt.copy_file': { schema: CopyFileSchema, handler: copyFile },
    'agent_mgmt.list_available_tools': {
        schema: z.object({}),
        handler: (deps: AgentMgmtDeps) => listAvailableTools(deps),
    },
} as const
