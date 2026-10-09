import { apiJson, apiStream, projectPath } from './client'

// Shapes follow `products/tasks/backend/presentation/serializers.py`, keeping the fields the app reads.

export type TaskRunStatusApi = 'not_started' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface TaskRunOutputApi {
    pr_url?: string | null
    pr_urls?: string[] | null
    head_branches?: string[] | null
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

export interface TaskRunCreateRequestApi {
    run_source: 'signal_report'
    signal_report_id: string
    mode: 'interactive'
    pending_user_message: string
    runtime_adapter: 'claude'
    model: string
    reasoning_effort: 'high'
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
            json: { jsonrpc: '2.0', id: options.id, method: command.method, params: command.params },
            signal: options.signal,
        }
    )
}
