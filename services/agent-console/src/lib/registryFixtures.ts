/**
 * Shared type shapes for registry detail pages.
 *
 * These were originally used to mock the registry while the backend was
 * being designed. The list/detail pages now hit the real API; the
 * type definitions remain because the detail components (`SkillDetail`,
 * `CustomToolDetail`) consume a *merged* shape — the per-version
 * detail plus the separately-loaded `history` and `usages` lists — and
 * it's cleaner to keep that compound shape named in one place than to
 * inline it in every consumer.
 */

export interface SkillTemplateSummary {
    /** UUID. */
    id: string
    /** Slug. `@posthog/<name>` for canonical PostHog-owned templates. */
    name: string
    description: string
    version: number
    is_latest: boolean
    /** Total file count including the index body. */
    file_count: number
    /** When this version was published. */
    updated_at: string
    /** First-name display from the publisher. `null` for canonical. */
    created_by: string | null
    /** Number of agent revisions currently pinning this template. */
    usage_count: number
}

export interface SkillTemplateDetail extends SkillTemplateSummary {
    /** Index markdown — `SKILL.md` equivalent. */
    body: string
    /** Companion files inside the skill folder (path relative to the skill root). */
    files: Array<{ path: string; content: string }>
    /** Older versions, newest first (excluding the current one). */
    history: Array<{ version: number; updated_at: string; created_by: string | null; note?: string }>
    /** Agent revisions currently pinning this template (any version). */
    usages: Array<{ agent_slug: string; agent_name: string; revision_short_id: string; pinned_version: number }>
}

export interface CustomToolTemplateSummary {
    id: string
    name: string
    description: string
    version: number
    is_latest: boolean
    /** Names of secrets the tool reads via `ctx.secret(...)`. */
    requires_secrets: string[]
    updated_at: string
    created_by: string | null
    usage_count: number
}

export interface CustomToolTemplateDetail extends CustomToolTemplateSummary {
    source: string
    /** Last compiled JS (read-only in v1; client-side rebuild on publish). */
    compiled_js: string
    /** TypeBox / JSON Schema for tool args. */
    args_schema: Record<string, unknown>
    /** Optional, informational. */
    returns_schema?: Record<string, unknown>
    history: Array<{ version: number; updated_at: string; created_by: string | null; note?: string }>
    usages: Array<{ agent_slug: string; agent_name: string; revision_short_id: string; pinned_version: number }>
}
