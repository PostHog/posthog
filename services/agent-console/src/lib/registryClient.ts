/**
 * Registry-specific REST client.
 *
 * Lives separate from `apiClient.ts` so registry-only changes don't
 * touch the shared client surface. Same fetch / error conventions, so
 * call sites compose naturally.
 *
 * Type shape comes from the generated `agent-platform.api.schemas.ts`
 * (synced from the Django `agent_platform` serializers via
 * `services/agent-console/bin/sync-api-schema.mjs`). When the backend
 * shape changes, rerun `hogli build:openapi` and the typed shape here
 * follows automatically.
 */

import type {
    CustomToolTemplateCreateApi,
    CustomToolTemplateDetailApi,
    CustomToolTemplateDuplicateApi,
    CustomToolTemplatePublishApi,
    CustomToolTemplateSummaryApi,
    CustomToolTemplateUsageApi,
    SkillTemplateCreateApi,
    SkillTemplateDetailApi,
    SkillTemplateDuplicateApi,
    SkillTemplateFileApi,
    SkillTemplateFileRenameApi,
    SkillTemplateFileWriteApi,
    SkillTemplatePublishApi,
    SkillTemplateSummaryApi,
    SkillTemplateUsageApi,
    TemplateVersionEntryApi,
} from './registryApiTypes'

// ── error shape ────────────────────────────────────────────────────────────

export class RegistryApiError extends Error {
    constructor(
        public readonly status: number,
        public readonly detail: string,
        public readonly extra?: Record<string, unknown>
    ) {
        super(detail)
    }
}

async function rawFetch(method: string, url: string, body?: unknown): Promise<Response> {
    return fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: body !== undefined ? JSON.stringify(body) : undefined,
    })
}

async function handle<T>(res: Response): Promise<T> {
    if (res.ok) {
        if (res.status === 204) {
            return undefined as T
        }
        return (await res.json()) as T
    }
    let detail = res.statusText
    let extra: Record<string, unknown> | undefined
    try {
        const body = await res.json()
        detail = typeof body?.detail === 'string' ? body.detail : detail
        extra = body?.extra
    } catch {
        // not JSON
    }
    throw new RegistryApiError(res.status, detail, extra)
}

function base(teamId: number, kind: 'skill' | 'tool'): string {
    return kind === 'skill'
        ? `/api/projects/${teamId}/agent_skill_templates`
        : `/api/projects/${teamId}/agent_custom_tool_templates`
}

// ── skill templates ───────────────────────────────────────────────────────

export async function listSkillTemplates(teamId: number, search?: string): Promise<SkillTemplateSummaryApi[]> {
    const q = search ? `?search=${encodeURIComponent(search)}` : ''
    return handle(await rawFetch('GET', `${base(teamId, 'skill')}/${q}`))
}

export async function getSkillTemplate(
    teamId: number,
    name: string,
    version?: number
): Promise<SkillTemplateDetailApi> {
    const q = version !== undefined ? `?version=${version}` : ''
    return handle(await rawFetch('GET', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/${q}`))
}

export async function createSkillTemplate(
    teamId: number,
    body: SkillTemplateCreateApi
): Promise<SkillTemplateDetailApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'skill')}/`, body))
}

export async function publishSkillTemplate(
    teamId: number,
    name: string,
    body: SkillTemplatePublishApi
): Promise<SkillTemplateDetailApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/publish/`, body))
}

export async function archiveSkillTemplate(teamId: number, name: string): Promise<void> {
    return handle(await rawFetch('POST', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/archive/`))
}

export async function duplicateSkillTemplate(
    teamId: number,
    name: string,
    body: SkillTemplateDuplicateApi
): Promise<SkillTemplateDetailApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/duplicate/`, body))
}

export async function listSkillTemplateVersions(teamId: number, name: string): Promise<TemplateVersionEntryApi[]> {
    return handle(await rawFetch('GET', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/versions/`))
}

export async function listSkillTemplateUsages(
    teamId: number,
    name: string,
    pinnedVersion?: number
): Promise<SkillTemplateUsageApi[]> {
    const q = pinnedVersion !== undefined ? `?pinned_version=${pinnedVersion}` : ''
    return handle(await rawFetch('GET', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/usages/${q}`))
}

export async function createSkillTemplateFile(
    teamId: number,
    name: string,
    body: SkillTemplateFileWriteApi
): Promise<SkillTemplateFileApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/files/`, body))
}

export async function deleteSkillTemplateFile(teamId: number, name: string, filePath: string): Promise<void> {
    return handle(
        await rawFetch(
            'DELETE',
            `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/files/${encodeURIComponent(filePath)}/`
        )
    )
}

export async function renameSkillTemplateFile(
    teamId: number,
    name: string,
    body: SkillTemplateFileRenameApi
): Promise<SkillTemplateFileApi> {
    return handle(
        await rawFetch('POST', `${base(teamId, 'skill')}/name/${encodeURIComponent(name)}/files-rename/`, body)
    )
}

// ── custom tool templates ─────────────────────────────────────────────────

export async function listCustomToolTemplates(
    teamId: number,
    search?: string
): Promise<CustomToolTemplateSummaryApi[]> {
    const q = search ? `?search=${encodeURIComponent(search)}` : ''
    return handle(await rawFetch('GET', `${base(teamId, 'tool')}/${q}`))
}

export async function getCustomToolTemplate(
    teamId: number,
    name: string,
    version?: number
): Promise<CustomToolTemplateDetailApi> {
    const q = version !== undefined ? `?version=${version}` : ''
    return handle(await rawFetch('GET', `${base(teamId, 'tool')}/name/${encodeURIComponent(name)}/${q}`))
}

export async function createCustomToolTemplate(
    teamId: number,
    body: CustomToolTemplateCreateApi
): Promise<CustomToolTemplateDetailApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'tool')}/`, body))
}

export async function publishCustomToolTemplate(
    teamId: number,
    name: string,
    body: CustomToolTemplatePublishApi
): Promise<CustomToolTemplateDetailApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'tool')}/name/${encodeURIComponent(name)}/publish/`, body))
}

export async function archiveCustomToolTemplate(teamId: number, name: string): Promise<void> {
    return handle(await rawFetch('POST', `${base(teamId, 'tool')}/name/${encodeURIComponent(name)}/archive/`))
}

export async function duplicateCustomToolTemplate(
    teamId: number,
    name: string,
    body: CustomToolTemplateDuplicateApi
): Promise<CustomToolTemplateDetailApi> {
    return handle(await rawFetch('POST', `${base(teamId, 'tool')}/name/${encodeURIComponent(name)}/duplicate/`, body))
}

export async function listCustomToolTemplateVersions(teamId: number, name: string): Promise<TemplateVersionEntryApi[]> {
    return handle(await rawFetch('GET', `${base(teamId, 'tool')}/name/${encodeURIComponent(name)}/versions/`))
}

export async function listCustomToolTemplateUsages(
    teamId: number,
    name: string,
    pinnedVersion?: number
): Promise<CustomToolTemplateUsageApi[]> {
    const q = pinnedVersion !== undefined ? `?pinned_version=${pinnedVersion}` : ''
    return handle(await rawFetch('GET', `${base(teamId, 'tool')}/name/${encodeURIComponent(name)}/usages/${q}`))
}
