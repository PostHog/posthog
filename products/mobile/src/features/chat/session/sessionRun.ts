import type {
    ChatTaskCreateApi,
    PermissionModeApi,
    ReportDiscussionTaskCreateApi,
    RunRuntimeSelectionApi,
    RuntimeAdapterApi,
    SetConfigOptionParams,
    TaskRunApi,
    TaskRunCreateRequestApi,
} from '@/api/tasks'
import { HARNESS_LABELS, resolveModeForRuntimeAdapter } from '@/features/handoff/runOptions'
import type { AnalyticsProperties } from '@/lib/analytics'

import type { ChatRunOptions } from '../chatRunOptions'
import { bareQuestion, chatPrompt } from '../contextPrompt'
import type { ChatContext } from '../types'

// The request bodies and the live config sync of a chat on the task runtime. The web equivalents are
// `submitNewTask` in `taskTrackerSceneLogic.ts`, `createReportTask` in `inboxTaskKickoffLogic.ts`, and the
// `set_config_option` sync in `runInteractionLogic.ts`.

/** `signal_report_discussion_question`'s `max_length` in `TaskCreateSerializer`. */
const DISCUSSION_QUESTION_MAX_LENGTH = 4000
const TITLE_MAX_LENGTH = 255
const DISCUSSION_FALLBACK_TITLE = 'Discuss report'

/** The run fields a chat's options control. Without a runtime the server applies the stored default. */
type ChatRunFieldsApi = Partial<RunRuntimeSelectionApi> & { initial_permission_mode: PermissionModeApi }

export interface SessionRunConfig {
    runtimeAdapter: RuntimeAdapterApi | null
    /** Null when the run left the model to the agent server's own default. */
    model: string | null
    reasoningEffort: string | null
    permissionMode: string | null
}

export interface TrackedRunConfig extends SessionRunConfig {
    /**
     * The app changed `permissionMode` on the live run, so it wins over the mode the stream reported before. The next
     * mode the stream reports clears it (`withStreamModeReport`), as the web clears `sentMode` on `setCurrentMode`.
     */
    modeSetHere: boolean
}

export type RunSourceFieldsApi = Pick<TaskRunCreateRequestApi, 'run_source' | 'signal_report_id'>

interface ChatStartRequests {
    task: ChatTaskCreateApi | ReportDiscussionTaskCreateApi
    run: TaskRunCreateRequestApi
    fields: ChatRunFieldsApi
    /** Goes on every later fresh run of the task. Empty for a plain chat. */
    runSource: RunSourceFieldsApi
}

function asRuntimeAdapter(value: string | null | undefined): RuntimeAdapterApi | null {
    return value === 'claude' || value === 'codex' ? value : null
}

export function runSourceFields(signalReport: string | null | undefined): RunSourceFieldsApi {
    return signalReport ? { run_source: 'signal_report', signal_report_id: signalReport } : {}
}

/**
 * An untouched model sends only the mode, so the server applies the stored default, and with none the agent
 * server's own default. A pick sends the full triple with the mode mapped onto its harness, and no effort for a
 * model without effort control. `previous` is the run a resume continues, whose harness an untouched model keeps.
 */
export function chatRunFields(options: ChatRunOptions, previous?: SessionRunConfig | null): ChatRunFieldsApi {
    if (options.model === 'default') {
        const adapter = previous?.runtimeAdapter
        return {
            initial_permission_mode: adapter
                ? resolveModeForRuntimeAdapter(adapter, options.permissionMode)
                : options.permissionMode,
        }
    }
    const { runtimeAdapter, model, reasoningEffort } = options.model
    return {
        runtime_adapter: runtimeAdapter,
        model,
        ...(reasoningEffort ? { reasoning_effort: reasoningEffort } : {}),
        initial_permission_mode: resolveModeForRuntimeAdapter(runtimeAdapter, options.permissionMode),
    }
}

function runtimeSelection(fields: ChatRunFieldsApi): Partial<RunRuntimeSelectionApi> {
    const { initial_permission_mode: _mode, ...selection } = fields
    return selection
}

/**
 * The `POST tasks/` and `POST tasks/{id}/run/` bodies for a new chat. Exactly one attached report makes it an Inbox
 * "Discuss" task, which the server exempts from the PostHog Desktop gate. Anything else is a PostHog AI chat,
 * which the server names from the bare question.
 */
export function chatStartRequests(question: string, context: ChatContext, options: ChatRunOptions): ChatStartRequests {
    const prompt = chatPrompt(question, context)
    const fields = chatRunFields(options)
    const report = context.kind === 'reports' && context.reports.length === 1 ? context.reports[0] : undefined
    if (report) {
        const runSource = runSourceFields(report.reportId)
        return {
            task: {
                title: (report.title.trim() || DISCUSSION_FALLBACK_TITLE).slice(0, TITLE_MAX_LENGTH),
                description: prompt,
                origin_product: 'signal_report',
                signal_report: report.reportId,
                signal_report_task_relationship: 'discussion',
                // Undefanged, as the web sends it. Cut by code point, so the cut never splits a surrogate pair.
                signal_report_discussion_question: Array.from(question.trim())
                    .slice(0, DISCUSSION_QUESTION_MAX_LENGTH)
                    .join(''),
                ...runtimeSelection(fields),
                pending_user_message: prompt,
            },
            run: { ...runSource, mode: 'interactive', pending_user_message: prompt, ...fields },
            fields,
            runSource,
        }
    }
    return {
        task: {
            title: '',
            description: bareQuestion(question),
            origin_product: 'posthog_ai',
            ...fields,
            pending_user_message: prompt,
        },
        run: { mode: 'interactive', pending_user_message: prompt, ...fields },
        fields,
        runSource: {},
    }
}

/**
 * Puts staged attachment ids on a `run/` body. Only `run/` takes them: the task create takes ids only for a warm run,
 * and the app never claims one.
 */
export function withPendingArtifacts(
    body: TaskRunCreateRequestApi,
    artifactIds: readonly string[]
): TaskRunCreateRequestApi {
    return artifactIds.length > 0 ? { ...body, pending_user_artifact_ids: [...artifactIds] } : body
}

export function runConfigFromRun(run: TaskRunApi): TrackedRunConfig {
    return {
        runtimeAdapter: asRuntimeAdapter(run.runtime_adapter),
        model: run.model ?? null,
        reasoningEffort: run.reasoning_effort ?? null,
        permissionMode: run.state?.initial_permission_mode ?? null,
        modeSetHere: false,
    }
}

/**
 * The config of a run the app just started. The model it sent wins over what the response echoes. The mode is the
 * server's, which can clamp the one sent. The stream reports the starting mode too, so it is not marked as set here.
 */
export function runConfigAfterStart(run: TaskRunApi, fields: ChatRunFieldsApi): TrackedRunConfig {
    const opened = runConfigFromRun(run)
    return {
        runtimeAdapter: fields.runtime_adapter ?? opened.runtimeAdapter,
        model: fields.model ?? opened.model,
        reasoningEffort: fields.model ? (fields.reasoning_effort ?? null) : opened.reasoningEffort,
        permissionMode: opened.permissionMode ?? fields.initial_permission_mode,
        modeSetHere: false,
    }
}

export function currentPermissionMode(config: TrackedRunConfig, streamMode: string | undefined): string | null {
    return config.modeSetHere ? config.permissionMode : (streamMode ?? config.permissionMode)
}

/**
 * The stream reported a mode after the app set one. The agent can move on its own, such as out of Plan when a plan is
 * approved, so its report wins from now on.
 */
export function withStreamModeReport(config: TrackedRunConfig): TrackedRunConfig {
    return config.modeSetHere ? { ...config, modeSetHere: false } : config
}

type ConfigSyncPlan =
    | { type: 'changes'; changes: SetConfigOptionParams[]; permissionMode: PermissionModeApi }
    /** The pick is a model of the other harness, which a live run cannot switch to. */
    | { type: 'harness_mismatch'; runtimeAdapter: RuntimeAdapterApi }

/**
 * The `set_config_option` commands a send needs before its `user_message`: only values that differ from what the
 * run last had, in the web's order (model, effort, mode). An untouched model changes nothing about the model.
 */
export function configSyncPlan(
    options: ChatRunOptions,
    config: TrackedRunConfig,
    streamMode: string | undefined
): ConfigSyncPlan {
    const runtimeAdapter = config.runtimeAdapter ?? 'claude'
    const changes: SetConfigOptionParams[] = []
    if (options.model !== 'default') {
        const pinned = options.model
        if (pinned.runtimeAdapter !== runtimeAdapter) {
            return { type: 'harness_mismatch', runtimeAdapter }
        }
        if (pinned.model !== config.model) {
            changes.push({ configId: 'model', value: pinned.model })
        }
        if (pinned.reasoningEffort && pinned.reasoningEffort !== config.reasoningEffort) {
            changes.push({ configId: 'effort', value: pinned.reasoningEffort })
        }
    }
    const permissionMode = resolveModeForRuntimeAdapter(runtimeAdapter, options.permissionMode)
    if (permissionMode !== currentPermissionMode(config, streamMode)) {
        changes.push({ configId: 'mode', value: permissionMode })
    }
    return { type: 'changes', changes, permissionMode }
}

export function applyConfigChange(config: TrackedRunConfig, change: SetConfigOptionParams): TrackedRunConfig {
    switch (change.configId) {
        case 'model':
            return { ...config, model: change.value }
        case 'effort':
            return { ...config, reasoningEffort: change.value }
        case 'mode':
            return { ...config, permissionMode: change.value, modeSetHere: true }
    }
}

export function harnessMismatchMessage(runtimeAdapter: RuntimeAdapterApi): string {
    const harness = HARNESS_LABELS[runtimeAdapter]
    return `This chat runs on ${harness}. Pick a ${harness} model, or start a new chat.`
}

export function sentOptionProperties(options: ChatRunOptions, permissionMode: PermissionModeApi): AnalyticsProperties {
    if (options.model === 'default') {
        return { model: 'default', permission_mode: permissionMode }
    }
    return {
        model: options.model.model,
        ...(options.model.reasoningEffort ? { reasoning_effort: options.model.reasoningEffort } : {}),
        permission_mode: permissionMode,
    }
}
