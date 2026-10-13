import { ApiError, apiFetch, apiJson, apiStream, projectPath } from './client'

// Shapes follow `products/tasks/backend/presentation/serializers.py`, keeping the fields the app reads.

export type TaskRunStatusApi = 'not_started' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface TaskRunOutputApi {
    pr_url?: string | null
    pr_urls?: string[] | null
    head_branches?: string[] | null
}

export type TaskRuntimeAdapterApi = 'claude' | 'codex'

/** The part of `TaskRun.state` the app reads. The server stores more keys there. */
export interface TaskRunStateApi {
    resume_from_run_id?: string | null
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
    runtime_adapter?: TaskRuntimeAdapterApi | null
    model?: string | null
    reasoning_effort?: string | null
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

export interface TaskCreateRequestApi {
    title: string
    description: string
    origin_product: 'signal_report'
    signal_report: string
    signal_report_task_relationship: 'implementation'
}

/** `TaskRunCreateRequestSerializer`. A follow-up on an ended run sets `resume_from_run_id` and no run source. */
export interface TaskRunCreateRequestApi {
    run_source?: 'signal_report'
    signal_report_id?: string
    resume_from_run_id?: string
    mode: 'interactive'
    pending_user_message: string
    /** The server derives it from `model` when it is left out. */
    runtime_adapter?: TaskRuntimeAdapterApi
    model: string
    reasoning_effort?: string
}

export interface PermissionResponseParams {
    requestId: string
    optionId: string
    customInput?: string
    answers?: Record<string, string>
}

export interface UserMessageParams {
    content: string
}

export type TaskRunCommand =
    | { method: 'permission_response'; params: PermissionResponseParams }
    | { method: 'user_message'; params: UserMessageParams }
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
    archived: boolean
    latest_run: Pick<TaskRunApi, 'status' | 'output'> | null
    created_at: string | null
    updated_at: string | null
    last_activity_at: string | null
}

export const SESSION_LIST_LIMIT = 30

/** `created_by` filters on the numeric user id from `users/@me/`, not the UUID. */
export async function listMySessions(userId: number, signal?: AbortSignal): Promise<TaskSummaryApi[]> {
    const body = await apiJson<{ results?: TaskSummaryApi[] }>(projectPath('tasks/'), {
        query: { created_by: userId, ordering: '-last_activity_at', basic: true, limit: SESSION_LIST_LIMIT },
        signal,
    })
    return body.results ?? []
}
