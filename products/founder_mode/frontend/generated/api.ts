import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    FounderProjectApi,
    FounderProjectsListParams,
    PaginatedFounderProjectListApi,
    PatchedFounderProjectApi,
    PublishScaffoldRequestApi,
    TurnRequestApi,
    TurnResponseApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getFounderProjectsListUrl = (projectId: string, params?: FounderProjectsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/founder_projects/?${stringifiedParams}`
        : `/api/projects/${projectId}/founder_projects/`
}

/**
 * List the founder project for the current team (at most one row). Used by the frontend to find the existing project on session restore.
 */
export const founderProjectsList = async (
    projectId: string,
    params?: FounderProjectsListParams,
    options?: RequestInit
): Promise<PaginatedFounderProjectListApi> => {
    return apiMutator<PaginatedFounderProjectListApi>(getFounderProjectsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getFounderProjectsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/founder_projects/`
}

/**
 * Stage 1 (Ideation) commit. Called by the FE when the cofounder chat reaches `should_end_chat=true`. Body carries `{name, ideation: {what, how, who, problem}}`. **Side effect:** if `ideation` is non-empty, validation (stage 2) is auto-fired on commit — saves a round-trip vs creating then POSTing `run_validation/`. **Idempotent:** if a project already exists for this team, the existing row is updated and returned instead of creating a duplicate.
 */
export const founderProjectsCreate = async (
    projectId: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/`
}

/**
 * Get one founder project by id. **This is the poll target** — the frontend hits this every 2s while any stage is `running` and renders the appropriate envelope. One round-trip returns the state of all 5 stages.
 */
export const founderProjectsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getFounderProjectsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/`
}

/**
 * Full replace. Mainly used for renames. **Side effect:** if `ideation` changes, validation is re-fired automatically. Avoid sending unchanged ideation — re-runs burn a Gemini call.
 */
export const founderProjectsUpdate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/`
}

/**
 * Patch fields on a founder project. Same auto-revalidation as full update — sending a changed `ideation` re-fires the validation Celery task. Sending only `name` (or other non-ideation fields) is the safe rename path.
 */
export const founderProjectsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedFounderProjectApi?: NonReadonly<PatchedFounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedFounderProjectApi),
    })
}

export const getFounderProjectsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/`
}

/**
 * Delete a founder project row. Not wired in the FE today.
 */
export const founderProjectsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getFounderProjectsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getFounderProjectsPublishScaffoldCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/publish_scaffold/`
}

/**
 * **Stage 6b (Scaffold — publish).** Push the previously-generated file tree to a fresh GitHub repository on the authenticated user's account. Body carries the `github_token` (PAT with `repo` scope — used once, never persisted), `repo_name`, `visibility` (public/private), and optional `description`. Returns 202 + the project; poll `scaffold.status` and read `scaffold.repo` once it's `completed`. Requires `scaffold.files` to be populated by a prior `run_scaffold` call.
 */
export const founderProjectsPublishScaffoldCreate = async (
    projectId: string,
    id: string,
    publishScaffoldRequestApi: PublishScaffoldRequestApi,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsPublishScaffoldCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(publishScaffoldRequestApi),
    })
}

export const getFounderProjectsRunGtmCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/run_gtm/`
}

/**
 * **Stage 3 (GTM).** Generate the *conceptual* GTM summary — positioning statement, primary + secondary target segments, category, moat, pricing philosophy and tiers, primary + secondary acquisition channels. Single Gemini call grounded on `ideation` + `validation.report`. NOT the practical launch playbook (that's `run_practical_steps`). Writes to the `gtm` column. Poll until `gtm.status` is `completed` or `failed`.
 */
export const founderProjectsRunGtmCreate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRunGtmCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsRunLandingPageCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/run_landing_page/`
}

/**
 * **Stage 5 (Marketing) — landing page half.** Generate the landing page *build spec* (copy hooks, design notes, shadcn/ui component recipes, PostHog event signatures, acceptance criteria) from the full project state. NOT a rendered page — a brief a developer or AI coding agent takes and turns into Next.js + Tailwind code. Writes to the `marketing_page` column. The marketing UI stage fires this in parallel with `run_practical_steps`. Poll until `marketing_page.status` is `completed` or `failed`.
 */
export const founderProjectsRunLandingPageCreate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRunLandingPageCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsRunMvpCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/run_mvp/`
}

/**
 * **Stage 4 (MVP).** Generate the MVP happy-path spec — one-liner, 3-7 step user journey from first touch to value delivered, must-have features, deliberately excluded features. Single Gemini call grounded on `ideation` + `validation` + `gtm`. Placeholder prompt — content shape may change as stage 4 stabilizes. Writes to the `mvp` column. Poll until `mvp.status` is `completed` or `failed`.
 */
export const founderProjectsRunMvpCreate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRunMvpCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsRunPracticalStepsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/run_practical_steps/`
}

/**
 * **Stage 5 (Marketing) — practical playbook half.** Generate the concrete launch checklist — ready-to-publish copy for Product Hunt, LinkedIn, Twitter, Reddit, HN, Indie Hackers, etc., ordered D-7 → launch day → D+7. Each step has a platform, timeline, and full post text the founder can copy-paste. Writes to the `marketing_steps` column. The marketing UI stage fires this in parallel with `run_landing_page`. Poll until `marketing_steps.status` is `completed` or `failed`.
 */
export const founderProjectsRunPracticalStepsCreate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRunPracticalStepsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsRunScaffoldCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/run_scaffold/`
}

/**
 * **Stage 6a (Scaffold — generate).** Render the landing page build spec into a Next.js + Tailwind + react-markdown file tree, stored as `{path: contents}` on the `scaffold.files` column. Requires `marketing_page.status='completed'` (i.e. the spec exists). Pure Python — no LLM call, no network — should complete in well under a second. Poll until `scaffold.status` is `completed` or `failed`.
 */
export const founderProjectsRunScaffoldCreate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRunScaffoldCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsRunValidationCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/founder_projects/${id}/run_validation/`
}

/**
 * **Stage 2 (Validation).** Kick off the two-pass competitor research + assumptions report against the current `ideation` payload. Two sequential Gemini calls — grounded search, then structured synthesis — ~30-60s end to end. Writes to the `validation` column with intermediate `current_pass` updates so the FE can show real staged progress. Poll the detail endpoint until `validation.status` is `completed` or `failed`.
 */
export const founderProjectsRunValidationCreate = async (
    projectId: string,
    id: string,
    founderProjectApi: NonReadonly<FounderProjectApi>,
    options?: RequestInit
): Promise<FounderProjectApi> => {
    return apiMutator<FounderProjectApi>(getFounderProjectsRunValidationCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(founderProjectApi),
    })
}

export const getFounderProjectsCofounderTurnCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/founder_projects/cofounder_turn/`
}

/**
 * **Stage 1 (Ideation).** One turn of a topic-scoped cofounder mini-chat. Synchronous Gemini call. The request carries `{topic, goal, user_answer, messages, founder_mode}` — the topic's whole thread so far (chat is ephemeral on the FE). The response carries the agent's next `agent_message`, a `satisfied` flag, and — when satisfied — a `crystallized_value` dict whose keys are defined by the request `goal` (for the `idea` topic: `{what, how, who, problem}`). On `satisfied=true` the FE POSTs the crystallized value to `founder_projects/` to commit the ideation and auto-fire validation (stage 2).
 */
export const founderProjectsCofounderTurnCreate = async (
    projectId: string,
    turnRequestApi: TurnRequestApi,
    options?: RequestInit
): Promise<TurnResponseApi> => {
    return apiMutator<TurnResponseApi>(getFounderProjectsCofounderTurnCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(turnRequestApi),
    })
}
