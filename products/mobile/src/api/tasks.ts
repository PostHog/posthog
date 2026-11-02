import { ApiError, apiFetch, apiJson, apiStream, projectPath } from './client'

// Shapes follow `products/tasks/backend/presentation/serializers.py`, keeping the fields the app reads.

export type TaskRunStatusApi = 'not_started' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface TaskRunOutputApi {
    pr_url?: string | null
    pr_urls?: string[] | null
    head_branches?: string[] | null
}

/** The part of `TaskRun.state` the app reads. The server stores more keys there. */
export interface TaskRunStateApi {
    resume_from_run_id?: string | null
    initial_permission_mode?: string | null
}

export interface TaskRunApi {
    id: string
    task: string
    status: TaskRunStatusApi
    stage: string | null
    branch: string | null
    error_message: string | null
    output: TaskRunOutputApi | null
    completed_at: string | null
    updated_at?: string
    runtime_adapter?: RuntimeAdapterApi | null
    model?: string | null
    reasoning_effort?: ReasoningEffortApi | null
    state?: TaskRunStateApi | null
}

export interface TaskApi {
    id: string
    title: string
    signal_report: string | null
    latest_run: TaskRunApi | null
}

export interface TaskCreateResponseApi extends TaskApi {
    run_error?: string
}

export interface TaskRunResponseApi extends TaskCreateResponseApi {
    /** The run this call created or activated. Older backends only fill `latest_run`. */
    run?: TaskRunApi | null
}

/** The Inbox "Create PR" task. The server resolves the repository and rejects one the client sets. */
interface ReportImplementationTaskCreateApi {
    title: string
    description: string
    origin_product: 'signal_report'
    signal_report: string
    signal_report_task_relationship: 'implementation'
}

/**
 * A PostHog AI chat, as the web side panel creates it. A blank title makes the server name the task from
 * `description`. It sends no `branch`: that key would let the create claim a warm run a web composer booted.
 */
export interface ChatTaskCreateApi extends Partial<RunRuntimeSelectionApi> {
    title: ''
    description: string
    origin_product: 'posthog_ai'
    initial_permission_mode: PermissionModeApi
    pending_user_message: string
}

/** The Inbox "Discuss" task. Repo-less report discussions are exempt from the PostHog Desktop gate. */
export interface ReportDiscussionTaskCreateApi extends Partial<RunRuntimeSelectionApi> {
    title: string
    description: string
    origin_product: 'signal_report'
    signal_report: string
    signal_report_task_relationship: 'discussion'
    /** Forwarded to the report's scout. At most 4000 characters. */
    signal_report_discussion_question?: string
    pending_user_message: string
}

/** `TaskCreateSerializer`, in the three shapes the app sends. */
export type TaskCreateRequestApi = ReportImplementationTaskCreateApi | ChatTaskCreateApi | ReportDiscussionTaskCreateApi

export type RuntimeAdapterApi = 'claude' | 'codex'

/** `REASONING_EFFORTS` in `products/tasks/backend/model_catalog.py`. */
export type ReasoningEffortApi = 'low' | 'medium' | 'high' | 'xhigh' | 'max' | 'ultracode'

/** `INITIAL_PERMISSION_MODE_CHOICES` (Claude) and `CODEX_INITIAL_PERMISSION_MODE_CHOICES` (Codex). */
export type PermissionModeApi =
    | 'default'
    | 'acceptEdits'
    | 'plan'
    | 'bypassPermissions'
    | 'auto'
    | 'read-only'
    | 'full-access'

/** The pinned model fields of `TaskRunCreateRequestSerializer`. The server needs `runtime_adapter` with `model`. */
export interface RunRuntimeSelectionApi {
    runtime_adapter: RuntimeAdapterApi
    model: string
    /** Left out for a model with no effort control, which rejects any value. */
    reasoning_effort?: ReasoningEffortApi
}

/** The run fields the hand-off options control. Without a runtime the server resolves the user's, then the team's, default. */
export interface HandoffRunFieldsApi extends Partial<RunRuntimeSelectionApi> {
    initial_permission_mode?: PermissionModeApi
    /** Base branch to check out in the sandbox. Left out for the repository's default branch. */
    branch?: string
}

/**
 * `TaskRunCreateRequestSerializer`. A follow-up on an ended run sets `resume_from_run_id` and no run source; without
 * a runtime it keeps the ended run's selection.
 */
export interface TaskRunCreateRequestApi extends HandoffRunFieldsApi {
    run_source?: 'signal_report'
    signal_report_id?: string
    resume_from_run_id?: string
    mode: 'interactive'
    pending_user_message: string
    /** Staged artifact ids from `staged_artifacts/finalize_upload/`. The server copies them into the new run. */
    pending_user_artifact_ids?: string[]
}

export interface ModelChoiceApi {
    runtime_adapter: RuntimeAdapterApi
    model: string
    display_name: string
    /** Ascending. Empty for a model with no effort control. */
    supported_efforts: ReasoningEffortApi[]
    /** Ready to display, such as `2×`. Null when the catalogue quotes no rate. */
    cost_multiplier?: string | null
}

/** `TasksResolvedAIRunDefaultsSerializer`: what a run uses when it pins no runtime. */
export interface ResolvedAiRunDefaultsApi {
    runtime: 'acp' | 'pi'
    /** Null when no default is stored or the harness is Pi. */
    runtime_adapter: string | null
    model: string | null
    reasoning_effort: string | null
    source: 'user' | 'team' | 'none'
}

export interface TaskUserConfigApi {
    resolved_ai_run_defaults: ResolvedAiRunDefaultsApi
}

export interface PermissionResponseParams {
    requestId: string
    optionId: string
    customInput?: string
    answers?: Record<string, string>
}

export interface UserMessageParams {
    content: string
    /** Joins the agent's live turn. The server queues the message as an ordinary follow-up when the agent declines. */
    steer?: boolean
    /** Artifact ids already on this run's manifest, from `runs/{r}/artifacts/finalize_upload/`. */
    artifact_ids?: string[]
}

type SessionConfigId = 'model' | 'effort' | 'mode'

export interface SetConfigOptionParams {
    configId: SessionConfigId
    value: string
}

export type TaskRunCommand =
    | { method: 'permission_response'; params: PermissionResponseParams }
    | { method: 'user_message'; params: UserMessageParams }
    | { method: 'set_config_option'; params: SetConfigOptionParams }
    | { method: 'cancel' }

/** JSON-RPC reply from `command/`. HTTP 200 can still carry an `error`. */
export interface TaskRunCommandResponseApi {
    jsonrpc?: string
    id?: string | number | null
    result?: unknown
    error?: { code?: number; message?: string }
}

export interface TaskRequestOptions {
    signal?: AbortSignal
    headers?: Record<string, string>
}

export function createTask(
    body: TaskCreateRequestApi,
    options: TaskRequestOptions = {}
): Promise<TaskCreateResponseApi> {
    return apiJson<TaskCreateResponseApi>(projectPath('tasks/'), { method: 'POST', json: body, ...options })
}

export function startTaskRun(
    taskId: string,
    body: TaskRunCreateRequestApi,
    options: TaskRequestOptions = {}
): Promise<TaskRunResponseApi> {
    return apiJson<TaskRunResponseApi>(projectPath(`tasks/${encodeURIComponent(taskId)}/run/`), {
        method: 'POST',
        json: body,
        ...options,
    })
}

/**
 * Where an upload goes. `staged` holds files on a task whose run does not exist yet, and `run` adds them to a live
 * run's manifest. Both take and return the same shapes.
 */
export type ArtifactUploadTarget = { kind: 'staged'; taskId: string } | { kind: 'run'; taskId: string; runId: string }

/** `TaskStagedArtifactPrepareUploadSerializer` and `TaskRunArtifactPrepareUploadSerializer`, for a user attachment. */
export interface ArtifactPrepareRequestApi {
    name: string
    type: 'user_attachment'
    source: 'posthog_ai'
    size: number
    content_type: string
}

export interface PresignedPostApi {
    url: string
    fields: Record<string, string>
}

/** `TaskStagedArtifactPrepareUploadResponseSerializer`. The array keeps the request's order. */
export interface PreparedArtifactApi {
    id: string
    name: string
    storage_path: string
    content_type?: string
    presigned_post: PresignedPostApi
}

/** `TaskStagedArtifactFinalizeUploadSerializer` and `TaskRunArtifactFinalizeUploadSerializer`. */
export interface ArtifactFinalizeRequestApi {
    id: string
    name: string
    type: 'user_attachment'
    source: 'posthog_ai'
    storage_path: string
    content_type: string
}

function artifactUploadPath(target: ArtifactUploadTarget, step: 'prepare_upload' | 'finalize_upload'): string {
    const task = `tasks/${encodeURIComponent(target.taskId)}`
    return target.kind === 'staged'
        ? projectPath(`${task}/staged_artifacts/${step}/`)
        : projectPath(`${task}/runs/${encodeURIComponent(target.runId)}/artifacts/${step}/`)
}

export async function prepareArtifactUpload(
    target: ArtifactUploadTarget,
    artifacts: ArtifactPrepareRequestApi[],
    signal?: AbortSignal
): Promise<PreparedArtifactApi[]> {
    const body = await apiJson<{ artifacts?: PreparedArtifactApi[] }>(artifactUploadPath(target, 'prepare_upload'), {
        method: 'POST',
        json: { artifacts },
        signal,
    })
    return body.artifacts ?? []
}

export async function finalizeArtifactUpload(
    target: ArtifactUploadTarget,
    artifacts: ArtifactFinalizeRequestApi[],
    signal?: AbortSignal
): Promise<void> {
    await apiJson<unknown>(artifactUploadPath(target, 'finalize_upload'), {
        method: 'POST',
        json: { artifacts },
        signal,
    })
}

/** `PATCH tasks/{id}/`. The server stamps `archived_at` and leaves an archived task out of the default list. */
export async function setTaskArchived(taskId: string, archived: boolean, signal?: AbortSignal): Promise<void> {
    await apiJson<unknown>(projectPath(`tasks/${encodeURIComponent(taskId)}/`), {
        method: 'PATCH',
        json: { archived },
        signal,
    })
}

/** Soft-deletes the task. It does not stop a run that already started. */
export async function deleteTask(taskId: string, signal?: AbortSignal): Promise<void> {
    await apiJson<unknown>(projectPath(`tasks/${encodeURIComponent(taskId)}/`), { method: 'DELETE', signal })
}

/** Every model a run may use, from the live gateway catalogue. Empty when the gateway is unreachable. */
export async function getTaskModels(signal?: AbortSignal): Promise<ModelChoiceApi[]> {
    const body = await apiJson<{ models?: ModelChoiceApi[] }>(projectPath('tasks/models/'), { signal })
    return body.models ?? []
}

export function getMyTaskConfig(signal?: AbortSignal): Promise<TaskUserConfigApi> {
    return apiJson<TaskUserConfigApi>(projectPath('tasks/@me/config/'), { signal })
}

export function getTask(taskId: string, signal?: AbortSignal): Promise<TaskApi> {
    return apiJson<TaskApi>(projectPath(`tasks/${encodeURIComponent(taskId)}/`), { signal })
}

export function getTaskRun(taskId: string, runId: string, signal?: AbortSignal): Promise<TaskRunApi> {
    return apiJson<TaskRunApi>(projectPath(`tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/`), {
        signal,
    })
}

/** The stored run log, one JSON record per line. A resumed run's log starts with its ancestors' logs, oldest first. */
export async function getTaskRunLogs(taskId: string, runId: string, signal?: AbortSignal): Promise<unknown[]> {
    const response = await apiFetch(
        projectPath(`tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/logs/`),
        { signal }
    )
    const text = await response.text()
    if (!response.ok) {
        throw new ApiError(response.status, parseJsonLine(text), response.headers)
    }
    return parseJsonLines(text)
}

function parseJsonLine(line: string): unknown {
    try {
        return JSON.parse(line) as unknown
    } catch {
        return undefined
    }
}

export function parseJsonLines(text: string): unknown[] {
    const records: unknown[] = []
    for (const line of text.split('\n')) {
        const trimmed = line.trim()
        if (!trimmed) {
            continue
        }
        const record = parseJsonLine(trimmed)
        if (record !== undefined) {
            records.push(record)
        }
    }
    return records
}

// Without `lastEventId` the server replays the durable run log first, which is how a question asked before the app
// connected reaches the decision card.
export function openTaskRunStream(
    taskId: string,
    runId: string,
    options: { lastEventId?: string; signal?: AbortSignal } = {}
): Promise<Response> {
    return apiStream(projectPath(`tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/stream/`), {
        signal: options.signal,
        headers: options.lastEventId ? { 'Last-Event-ID': options.lastEventId } : undefined,
    })
}

export function sendTaskRunCommand(
    taskId: string,
    runId: string,
    command: TaskRunCommand,
    options: { id: string; signal?: AbortSignal }
): Promise<TaskRunCommandResponseApi> {
    return apiJson<TaskRunCommandResponseApi>(
        projectPath(`tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}/command/`),
        {
            method: 'POST',
            json: {
                jsonrpc: '2.0',
                id: options.id,
                method: command.method,
                ...('params' in command ? { params: command.params } : {}),
            },
            signal: options.signal,
        }
    )
}

/** `TaskBasicApi` in `products/tasks/frontend/generated/api.schemas.ts`, the `basic=true` list shape. */
export interface TaskSummaryApi {
    id: string
    title: string
    /** `TaskOriginProduct`, such as `posthog_ai` for a chat or `signal_report` for a report hand-off. */
    origin_product: string
    archived: boolean
    latest_run: Pick<TaskRunApi, 'status' | 'output'> | null
    created_at: string | null
    updated_at: string | null
    last_activity_at: string | null
}

export const SESSION_LIST_LIMIT = 30

// Scout runs are headless, not conversations. The web PostHog AI task list leaves them out the same way.
const SCOUT_ORIGIN_PRODUCT = 'signals_scout'

/** `created_by` filters on the numeric user id from `users/@me/`, not the UUID. */
export async function listMySessions(userId: number, signal?: AbortSignal): Promise<TaskSummaryApi[]> {
    const body = await apiJson<{ results?: TaskSummaryApi[] }>(projectPath('tasks/'), {
        query: {
            created_by: userId,
            ordering: '-last_activity_at',
            basic: true,
            limit: SESSION_LIST_LIMIT,
            exclude_origin_product: SCOUT_ORIGIN_PRODUCT,
        },
        signal,
    })
    return body.results ?? []
}
