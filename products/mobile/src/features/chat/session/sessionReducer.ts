import type { FrameContext } from '@/features/handoff/runStream'
import { extractAgentToolName, isPostHogExecTool, resolveToolCall } from '@/features/handoff/toolPolicy'
import { describeToolCall } from '@/features/handoff/toolTitle'
import { asRecord, isRecord } from '@/lib/records'

import { isImageName } from '../attachments/attachmentRules'
import { stripInjectedContext } from '../contextPrompt'
import type {
    SessionAssistantItem,
    SessionAttachment,
    SessionErrorItem,
    SessionNoticeItem,
    SessionProgressItem,
    SessionProgressStep,
    SessionThoughtItem,
    SessionThreadItem,
    SessionToolInvocation,
    SessionToolStatus,
} from './types'

// Mirrors `foldLogToThread` in `products/posthog_ai/frontend/logics/runStreamLogic.ts`, without timestamps and debug
// rows, which the phone does not draw.

/** The agent server writes this prompt into a resume run's log before the real message. It is not the person's. */
const RESUME_CONTEXT_PREFIX = 'You are resuming a previous conversation.'

// A queued send echoes when the agent takes it up, which is at most a turn later, so after two boundaries the echo
// can no longer pair with the bubble.
const SETTLED_AFTER_TURNS = 2

const AGENT_ERROR = 'The agent ran into an error.'
const AGENT_STOPPED = 'The agent stopped before it finished this request.'
const NOT_DELIVERED = "Your message didn't reach the agent."

const SPINNING_STATUS_TEXT: Record<string, string> = {
    compacting: 'Compacting the conversation',
    clearing: 'Clearing the conversation',
}

interface WaitingSend {
    id: string
    text: string
    turns: number
}

/** What the `tool_call` frame said, so a later update can still name the tool. */
interface RawToolCall {
    server: string
    tool: string
    input: Record<string, unknown>
    meta: unknown
}

export interface SessionThreadState {
    items: SessionThreadItem[]
    invocations: ReadonlyMap<string, SessionToolInvocation>
    rawToolCalls: ReadonlyMap<string, RawToolCall>
    /** Optimistic sends with no echo yet, oldest first. Their items stay at the foot of the thread. */
    waiting: readonly WaitingSend[]
    /** The thread belongs to a resume run, so the resume context prompt is not drawn. */
    resumeRun: boolean
    /** The next replayed frame starts the thread again, because the server replays the whole run log. */
    rebuildPending: boolean
    /** Replayed texts a `_posthog/user_message` drew, so the same turn's `user_message_chunk` does not draw it again. */
    replayedHumanTexts: ReadonlyMap<string, number>
    /** Live sends this turn already placed, so the second wire form of the same send draws nothing. */
    pairedSends: ReadonlyMap<string, number>
    /**
     * The device file behind each artifact a send carried. A rebuild draws the thread again from the log, which has
     * no local URI, so the previews come back from here.
     */
    localPreviews: ReadonlyMap<string, string>
    counters: Readonly<Record<CounterKey, number>>
}

type CounterKey = 'user' | 'bubble' | 'turn' | 'error' | 'notice'

export interface SessionFrame {
    frame: unknown
    context: FrameContext
}

export type SessionThreadAction =
    | { type: 'frame'; frame: unknown; context: FrameContext }
    | { type: 'frames'; frames: readonly SessionFrame[] }
    /** `echo: false` for text the agent never echoes, such as an answered decision. */
    | { type: 'local_user'; id: string; text: string; echo?: boolean; attachments?: SessionAttachment[] }
    /** Takes back an optimistic send that did not reach the server. */
    | { type: 'withdraw'; id: string }
    /** `resumeRun` when the run the thread follows now resumes an earlier one. */
    | { type: 'resuming'; resumeRun?: boolean }
    | { type: 'settle' }
    | { type: 'reset'; resumeRun?: boolean }

const ZERO_COUNTERS: Record<CounterKey, number> = { user: 0, bubble: 0, turn: 0, error: 0, notice: 0 }

export function initialSessionThread(resumeRun = false): SessionThreadState {
    return {
        items: [],
        invocations: new Map(),
        rawToolCalls: new Map(),
        waiting: [],
        resumeRun,
        rebuildPending: false,
        replayedHumanTexts: new Map(),
        pairedSends: new Map(),
        localPreviews: new Map(),
        counters: ZERO_COUNTERS,
    }
}

export function visibleUserText(raw: string): string {
    return stripInjectedContext(raw)
}

function isHiddenUserContent(content: unknown): boolean {
    return asRecord(asRecord(asRecord(content)?._meta)?.ui)?.hidden === true
}

function uriPathSegments(uri: string): string[] {
    // React Native's `URL` has no `pathname`, so the scheme, host, query and fragment come off by hand.
    const path = uri.replace(/^[a-z][a-z0-9+.-]*:\/\/[^/]*/i, '').split(/[?#]/)[0] ?? ''
    return path.split('/').filter(Boolean)
}

function decodeSegment(segment: string): string {
    try {
        return decodeURIComponent(segment)
    } catch {
        return segment
    }
}

/**
 * The agent server writes each file to `.posthog/attachments/<runId>/<artifactId>/<name>`, and that path is the only
 * place the wire carries the ids. Any other path keeps only the name.
 */
function artifactRefFromUri(uri: string): Pick<SessionAttachment, 'runId' | 'artifactId'> {
    const segments = uriPathSegments(uri)
    const marker = segments.lastIndexOf('attachments')
    if (marker < 1 || segments[marker - 1] !== '.posthog' || segments.length < marker + 4) {
        return {}
    }
    return { runId: segments[marker + 1] as string, artifactId: segments[marker + 2] as string }
}

function userAttachment(content: unknown): SessionAttachment | undefined {
    const block = asRecord(content)
    if (block?.type !== 'resource_link' && block?.type !== 'image') {
        return undefined
    }
    const uri = typeof block.uri === 'string' ? block.uri : ''
    const named = typeof block.name === 'string' ? block.name.trim() : ''
    const fromUri = uri ? uriPathSegments(uri).at(-1) : undefined
    const name = named || (fromUri ? decodeSegment(fromUri) : '')
    if (!name) {
        return undefined
    }
    return { name, isImage: block.type === 'image' || isImageName(name), ...(uri ? artifactRefFromUri(uri) : {}) }
}

/**
 * Identity is the artifact, never the name, because two pasted screenshots are both `image.png`. A known artifact
 * merges into its entry, so a file echoed in both wire forms shows once. Otherwise the file fills the first entry of
 * that name with no artifact yet, which is what an optimistic send drew, and so keeps its local preview.
 */
function mergeAttachment(existing: readonly SessionAttachment[], incoming: SessionAttachment): SessionAttachment[] {
    const byArtifact = incoming.artifactId
        ? existing.findIndex((candidate) => candidate.artifactId === incoming.artifactId)
        : -1
    const target =
        byArtifact !== -1
            ? byArtifact
            : existing.findIndex((candidate) => candidate.name === incoming.name && !candidate.artifactId)
    if (target === -1) {
        return [...existing, incoming]
    }
    return existing.map((candidate, index) => (index === target ? { ...candidate, ...incoming } : candidate))
}

function userMessageText(content: unknown): string {
    if (typeof content === 'string') {
        return content
    }
    if (!Array.isArray(content)) {
        return ''
    }
    return content
        .filter((block) => !isHiddenUserContent(block))
        .map((block) => {
            const text = asRecord(block)?.text
            return typeof text === 'string' ? text : ''
        })
        .join('')
}

function asText(value: unknown): string | undefined {
    return typeof value === 'string' && value ? value : undefined
}

function toolStatus(status: unknown): SessionToolStatus {
    switch (status) {
        case 'in_progress':
        case 'completed':
        case 'failed':
            return status
        default:
            return 'pending'
    }
}

function progressStatus(status: unknown): SessionToolStatus {
    switch (status) {
        case 'pending':
        case 'in_progress':
        case 'completed':
            return status
        case 'failed':
        case 'cancelled':
            return 'failed'
        default:
            return 'in_progress'
    }
}

function claudeCodeMeta(meta: unknown): Record<string, unknown> | undefined {
    return asRecord(asRecord(meta)?.claudeCode)
}

/** A subagent's inner calls carry the parent Task call's id. They belong to that card, not the thread. */
function subagentParentToolCallId(meta: unknown): string | undefined {
    return asText(claudeCodeMeta(meta)?.parentToolCallId)
}

function denialReason(meta: unknown): string | undefined {
    const response = asRecord(claudeCodeMeta(meta)?.toolResponse)
    return asText(response?.decisionReason) ?? asText(response?.message)
}

/** The agent's own tool, else the inner PostHog tool behind the `exec` wrapper, else the raw ACP name. */
function toolDisplayName(raw: RawToolCall): string {
    const agentToolName = extractAgentToolName(raw.meta)
    const { innerToolName } = resolveToolCall({
        toolCallId: '',
        rawServerName: raw.server,
        rawToolName: raw.tool,
        input: raw.input,
        meta: raw.meta,
    })
    if (innerToolName) {
        return innerToolName
    }
    if (agentToolName && !isPostHogExecTool(agentToolName)) {
        return agentToolName
    }
    return raw.tool || agentToolName || ''
}

function toolInput(update: Record<string, unknown>): Record<string, unknown> | undefined {
    return asRecord(update.rawInput) ?? asRecord(update.input)
}

/** Mutable working copy for one action, so a replayed log of thousands of frames folds without a copy per frame. */
class Draft {
    items: SessionThreadItem[]
    invocations: Map<string, SessionToolInvocation>
    rawToolCalls: Map<string, RawToolCall>
    waiting: WaitingSend[]
    resumeRun: boolean
    rebuildPending: boolean
    replayedHumanTexts: Map<string, number>
    pairedSends: Map<string, number>
    localPreviews: Map<string, string>
    counters: Record<CounterKey, number>
    private readonly openAssistants = new Set<SessionAssistantItem>()
    private readonly openThoughts = new Set<SessionThoughtItem>()
    private readonly toolItemIds = new Set<string>()

    constructor(state: SessionThreadState) {
        this.items = state.items.map((item) => {
            if (item.kind === 'assistant' && !item.complete) {
                const copy = { ...item }
                this.openAssistants.add(copy)
                return copy
            }
            if (item.kind === 'thought' && !item.complete) {
                const copy = { ...item }
                this.openThoughts.add(copy)
                return copy
            }
            if (item.kind === 'tool') {
                this.toolItemIds.add(item.toolCallId)
            }
            return item
        })
        this.invocations = new Map(state.invocations)
        this.rawToolCalls = new Map(state.rawToolCalls)
        this.waiting = state.waiting.map((send) => ({ ...send }))
        this.resumeRun = state.resumeRun
        this.rebuildPending = state.rebuildPending
        this.replayedHumanTexts = new Map(state.replayedHumanTexts)
        this.pairedSends = new Map(state.pairedSends)
        this.localPreviews = new Map(state.localPreviews)
        this.counters = { ...state.counters }
    }

    toState(): SessionThreadState {
        return {
            items: this.items,
            invocations: this.invocations,
            rawToolCalls: this.rawToolCalls,
            waiting: this.waiting,
            resumeRun: this.resumeRun,
            rebuildPending: this.rebuildPending,
            replayedHumanTexts: this.replayedHumanTexts,
            pairedSends: this.pairedSends,
            localPreviews: this.localPreviews,
            counters: this.counters,
        }
    }

    private next(key: CounterKey): number {
        const value = this.counters[key]
        this.counters[key] = value + 1
        return value
    }

    private isWaiting(id: string): boolean {
        return this.waiting.some((send) => send.id === id)
    }

    /** Index where new content goes: above the sends the agent has not taken up yet. */
    private footIndex(): number {
        let index = this.items.length
        while (index > 0 && this.isWaiting((this.items[index - 1] as SessionThreadItem).id)) {
            index -= 1
        }
        return index
    }

    private push(item: SessionThreadItem): void {
        if (item.kind !== 'thought') {
            // A thought has no closing frame; anything that follows it is where the thought ended.
            for (const thought of this.openThoughts) {
                thought.complete = true
            }
            this.openThoughts.clear()
        }
        this.items.splice(this.footIndex(), 0, item)
        if (item.kind === 'assistant' && !item.complete) {
            this.openAssistants.add(item)
        } else if (item.kind === 'thought' && !item.complete) {
            this.openThoughts.add(item)
        } else if (item.kind === 'tool') {
            this.toolItemIds.add(item.toolCallId)
        }
    }

    private closeOpenBuffers(): void {
        for (const item of this.openAssistants) {
            item.complete = true
        }
        for (const item of this.openThoughts) {
            item.complete = true
        }
        this.openAssistants.clear()
        this.openThoughts.clear()
    }

    rebuild(): void {
        const waitingIds = new Set(this.waiting.map((send) => send.id))
        this.items = this.items.filter((item) => waitingIds.has(item.id))
        this.openAssistants.clear()
        this.openThoughts.clear()
        this.toolItemIds.clear()
        this.invocations = new Map()
        this.rawToolCalls = new Map()
        this.replayedHumanTexts = new Map()
        this.pairedSends = new Map()
        this.rebuildPending = false
    }

    localUser(id: string, text: string, echo: boolean, attachments: SessionAttachment[]): void {
        if (this.items.some((item) => item.id === id)) {
            return
        }
        const item: SessionThreadItem = { kind: 'user', id, text, ...(attachments.length > 0 ? { attachments } : {}) }
        if (echo) {
            this.items.push(item)
            this.waiting.push({ id, text, turns: 0 })
            return
        }
        this.closeOpenBuffers()
        this.push(item)
    }

    withdraw(id: string): void {
        this.waiting = this.waiting.filter((send) => send.id !== id)
        this.items = this.items.filter((item) => item.id !== id)
    }

    settle(): void {
        this.closeOpenBuffers()
        this.items = this.items.filter((item) => !(item.kind === 'notice' && item.spinning))
    }

    // ---- user messages ----

    private takeWaiting(text: string): string | undefined {
        const index = this.waiting.findIndex((send) => send.text === text)
        if (index === -1) {
            return undefined
        }
        const [send] = this.waiting.splice(index, 1)
        return send?.id
    }

    /** The echo says the agent took the send up, so its bubble leaves the foot and sits where the turn starts. */
    private placeEcho(waitingId: string): void {
        const index = this.items.findIndex((item) => item.id === waitingId)
        if (index === -1) {
            return
        }
        const [item] = this.items.splice(index, 1)
        if (item) {
            this.push(item)
        }
    }

    private currentTurnHasUserText(text: string): boolean {
        for (let index = this.items.length - 1; index >= 0; index -= 1) {
            const item = this.items[index]
            if (item?.kind === 'turn_end') {
                return false
            }
            if (item?.kind === 'user' && item.text === text && !this.isWaiting(item.id)) {
                return true
            }
        }
        return false
    }

    private pushUser(text: string): void {
        this.closeOpenBuffers()
        this.push({ kind: 'user', id: `user-${this.next('user')}`, text })
    }

    /** `primary` is the `_posthog/user_message` form; the `user_message_chunk` form of the same send follows it. */
    human(raw: string, source: FrameContext['source'], primary: boolean): void {
        const text = visibleUserText(raw)
        if (!text || (this.resumeRun && text.startsWith(RESUME_CONTEXT_PREFIX))) {
            return
        }
        const credits = source === 'replay' ? this.replayedHumanTexts : this.pairedSends
        if (!primary) {
            const credit = credits.get(text) ?? 0
            if (credit > 0) {
                credits.set(text, credit - 1)
                return
            }
        }
        const waitingId = this.takeWaiting(text)
        if (waitingId !== undefined) {
            this.placeEcho(waitingId)
        } else if (source === 'live' && this.currentTurnHasUserText(text)) {
            return
        } else {
            this.pushUser(text)
        }
        if (primary) {
            credits.set(text, (credits.get(text) ?? 0) + 1)
        }
    }

    /**
     * A message's files follow its text, in the same frame or the frames after it, so they belong to the latest user
     * bubble the agent took up. A send still waiting at the foot has not echoed, so it is never the target.
     */
    noteAttachment(incoming: SessionAttachment): void {
        const preview = incoming.artifactId ? this.localPreviews.get(incoming.artifactId) : undefined
        const attachment = preview && !incoming.localUri ? { ...incoming, localUri: preview } : incoming
        // A message with files and no text, which another client can send, has no bubble of its own, so its files
        // join the previous bubble, as on the web.
        for (let index = this.items.length - 1; index >= 0; index -= 1) {
            const item = this.items[index]
            if (item?.kind === 'user' && !this.isWaiting(item.id)) {
                const attachments = mergeAttachment(item.attachments ?? [], attachment)
                for (const merged of attachments) {
                    if (merged.artifactId && merged.localUri) {
                        this.localPreviews.set(merged.artifactId, merged.localUri)
                    }
                }
                this.items[index] = { ...item, attachments }
                return
            }
        }
    }

    // ---- agent text ----

    /** The open buffer a chunk continues: only while nothing but waiting sends came after it. */
    private continuableBuffer(wireId: string, kind: 'assistant' | 'thought'): number {
        const prefix = `${wireId}@`
        for (let index = this.items.length - 1; index >= 0; index -= 1) {
            const item = this.items[index] as SessionThreadItem
            if (item.kind === kind && item.id.startsWith(prefix)) {
                return item.complete ? -1 : index
            }
            if (!this.isWaiting(item.id)) {
                return -1
            }
        }
        return -1
    }

    appendChunk(wireId: string, kind: 'assistant' | 'thought', delta: string): void {
        if (!delta) {
            return
        }
        const index = this.continuableBuffer(wireId, kind)
        const existing = this.items[index]
        if ((existing?.kind === 'assistant' || existing?.kind === 'thought') && existing.kind === kind) {
            existing.text += delta
            return
        }
        // The wire often omits `messageId`, so every bubble gets its own sequence suffix to keep ids unique.
        this.push({ kind, id: `${wireId}@${this.next('bubble')}`, text: delta, complete: false })
    }

    finalizeMessage(wireId: string, text: string): void {
        const prefix = `${wireId}@`
        const open = [...this.openAssistants].reverse()
        // Chunks and their closing message do not always carry the same `messageId`, so close the open buffer.
        const existing = open.find((item) => item.id.startsWith(prefix)) ?? open[0]
        if (existing) {
            existing.text = text || existing.text
            existing.complete = true
            this.openAssistants.delete(existing)
            return
        }
        if (text) {
            // The usual replay case: the stored log drops chunks, so a finished message arrives alone.
            this.push({ kind: 'assistant', id: `${wireId}@${this.next('bubble')}`, text, complete: true })
        }
    }

    // ---- tools ----

    private ensureToolItem(toolCallId: string): void {
        if (!this.toolItemIds.has(toolCallId)) {
            this.push({ kind: 'tool', id: `tool-${toolCallId}`, toolCallId })
        }
    }

    toolCall(update: Record<string, unknown>): void {
        const toolCallId = asText(update.toolCallId)
        if (!toolCallId) {
            return
        }
        const raw: RawToolCall = {
            server: String(update.serverName ?? 'posthog'),
            tool: String(update.toolName ?? ''),
            input: toolInput(update) ?? {},
            meta: update._meta,
        }
        this.rawToolCalls.set(toolCallId, raw)
        const { title, detail } = describeToolCall(raw, asText(update.title))
        const kind = asText(update.kind)
        this.invocations.set(toolCallId, {
            toolCallId,
            toolName: toolDisplayName(raw),
            ...(title ? { title } : {}),
            ...(detail ? { detail } : {}),
            ...(kind ? { kind } : {}),
            status: toolStatus(update.status),
        })
        if (!subagentParentToolCallId(update._meta)) {
            this.ensureToolItem(toolCallId)
        }
    }

    toolCallUpdate(update: Record<string, unknown>, notificationError: string | undefined): void {
        const toolCallId = asText(update.toolCallId)
        if (!toolCallId) {
            return
        }
        const existing = this.invocations.get(toolCallId)
        const status = toolStatus(update.status ?? existing?.status)
        const errorMessage =
            asText(asRecord(update.error)?.message) ??
            (status === 'failed' ? (denialReason(update._meta) ?? notificationError) : undefined) ??
            existing?.errorMessage
        const previous = this.rawToolCalls.get(toolCallId)
        const raw: RawToolCall = {
            server: previous?.server ?? 'posthog',
            tool: previous?.tool ?? '',
            input: toolInput(update) ?? previous?.input ?? {},
            meta: update._meta ?? previous?.meta,
        }
        this.rawToolCalls.set(toolCallId, raw)
        const toolName = toolDisplayName(raw) || (existing?.toolName ?? '')
        const described = describeToolCall(raw, asText(update.title))
        const title = described.title ?? existing?.title
        const detail = described.detail ?? existing?.detail
        const kind = existing?.kind ?? asText(update.kind)
        this.invocations.set(toolCallId, {
            toolCallId,
            toolName,
            ...(title ? { title } : {}),
            ...(detail ? { detail } : {}),
            ...(kind ? { kind } : {}),
            status,
            ...(errorMessage ? { errorMessage } : {}),
        })
        // A reconnect can deliver the update without the call that created it; the row still shows.
        if (!existing && !subagentParentToolCallId(update._meta)) {
            this.ensureToolItem(toolCallId)
        }
    }

    // ---- run news ----

    turnEnd(): void {
        this.closeOpenBuffers()
        this.push({ kind: 'turn_end', id: `turn-${this.next('turn')}` })
        this.pairedSends.clear()
        for (const send of this.waiting) {
            send.turns += 1
        }
        this.waiting = this.waiting.filter((send) => send.turns < SETTLED_AFTER_TURNS)
    }

    /** Two frames often describe one failure with the same text; keep the shorter one. */
    error(message: string): void {
        const last = this.items[this.footIndex() - 1]
        if (last?.kind === 'error' && last.variant !== 'crash') {
            const a = last.message.trim()
            const b = message.trim()
            if (a.includes(b) || b.includes(a)) {
                this.items[this.footIndex() - 1] = { ...last, message: a.length <= b.length ? a : b }
                return
            }
        }
        // A follow-up that failed to deliver in this turn was a symptom of this error, so the two become one row.
        let turnStart = -1
        for (let index = this.items.length - 1; index >= 0; index -= 1) {
            if (this.items[index]?.kind === 'user') {
                turnStart = index
                break
            }
        }
        const undeliveredIndex = this.items.findIndex(
            (item, index) => index > turnStart && item.kind === 'error' && item.variant === 'undelivered'
        )
        if (undeliveredIndex !== -1) {
            this.items.splice(undeliveredIndex, 1)
        }
        const item: SessionErrorItem = {
            kind: 'error',
            id: `error-${this.next('error')}`,
            message,
            variant: undeliveredIndex !== -1 ? 'undelivered' : 'error',
        }
        this.push(item)
    }

    progress(params: Record<string, unknown>): void {
        const group = asText(params.group)
        const step = asText(params.step)
        const label = asText(params.label)
        const status = progressStatus(params.status)
        if (step === 'followup_delivery' && status === 'failed') {
            this.items = this.items.filter((item) => !(item.kind === 'progress' && item.id === `progress-${group}`))
            // The failed send is the last one drawn. It stays where it is instead of sinking below later answers.
            this.waiting.pop()
            const lastIndex = this.footIndex() - 1
            const last = this.items[lastIndex]
            if (last?.kind === 'error' && last.variant !== 'crash') {
                this.items[lastIndex] = { ...last, variant: 'undelivered' }
                return
            }
            this.push({
                kind: 'error',
                id: `error-${this.next('error')}`,
                message: asText(params.detail) ?? NOT_DELIVERED,
                variant: 'undelivered',
            })
            return
        }
        if (!group || !step || !label) {
            return
        }
        const detail = asText(params.detail)
        const nextStep: SessionProgressStep = { key: step, label, status, ...(detail ? { detail } : {}) }
        const id = `progress-${group}`
        const index = this.items.findIndex((item) => item.kind === 'progress' && item.id === id)
        const existing = this.items[index]
        if (existing?.kind !== 'progress') {
            const item: SessionProgressItem = { kind: 'progress', id, steps: [nextStep] }
            this.push(item)
            return
        }
        const stepIndex = existing.steps.findIndex((candidate) => candidate.key === step)
        const steps =
            stepIndex === -1
                ? [...existing.steps, nextStep]
                : existing.steps.map((candidate, i) => (i === stepIndex ? nextStep : candidate))
        this.items[index] = { ...existing, steps }
    }

    private notice(text: string, tone: SessionNoticeItem['tone'], idPrefix = 'notice', spinning = false): void {
        this.push({
            kind: 'notice',
            id: `${idPrefix}-${this.next('notice')}`,
            text,
            tone,
            ...(spinning ? { spinning: true } : {}),
        })
    }

    private retireSpinner(status: string): void {
        const prefix = `status-${status}-`
        this.items = this.items.filter(
            (item) => !(item.kind === 'notice' && item.spinning && item.id.startsWith(prefix))
        )
    }

    status(params: Record<string, unknown>): void {
        const status = String(params.status ?? '')
        const complete = params.isComplete === true
        if (status === 'clearing_failed') {
            // A failed clear sends no `conversation_cleared`, so the spinner ends here.
            this.retireSpinner('clearing')
            const reason = asText(params.error)
            this.notice(
                reason ? `Couldn't clear the conversation: ${reason}` : "Couldn't clear the conversation.",
                'failed'
            )
            return
        }
        const text = SPINNING_STATUS_TEXT[status]
        if (!text) {
            return
        }
        if (complete) {
            this.retireSpinner(status)
            return
        }
        this.notice(text, 'info', `status-${status}`, true)
    }

    compactBoundary(): void {
        this.retireSpinner('compacting')
        this.notice('Compacted the conversation', 'info')
    }

    conversationCleared(): void {
        this.retireSpinner('clearing')
        this.notice('Cleared the conversation', 'info')
    }

    taskNotification(params: Record<string, unknown>): void {
        const status = asText(params.status)
        const tone: SessionNoticeItem['tone'] =
            status === 'completed' ? 'completed' : status === 'failed' ? 'failed' : 'info'
        const fallback =
            tone === 'completed'
                ? 'A background task finished.'
                : tone === 'failed'
                  ? 'A background task failed.'
                  : 'A background task changed.'
        this.notice(asText(params.summary) ?? fallback, tone)
    }
}

function notificationOf(frame: unknown): Record<string, unknown> | undefined {
    const record = asRecord(frame)
    if (!record || (record.type !== undefined && record.type !== 'notification')) {
        return undefined
    }
    return asRecord(record.notification)
}

function applyUserUpdate(draft: Draft, update: Record<string, unknown>, source: FrameContext['source']): void {
    if (isHiddenUserContent(update.content)) {
        return
    }
    const attachment = userAttachment(update.content)
    if (attachment) {
        draft.noteAttachment(attachment)
        return
    }
    const content = asRecord(update.content)
    const text = typeof content?.text === 'string' ? content.text : typeof update.text === 'string' ? update.text : ''
    draft.human(text, source, false)
}

function messageText(update: Record<string, unknown>): string {
    const content = asRecord(update.content)
    if (typeof content?.text === 'string') {
        return content.text
    }
    return typeof update.text === 'string' ? update.text : ''
}

function applySessionUpdate(
    draft: Draft,
    update: Record<string, unknown>,
    notificationError: string | undefined,
    source: FrameContext['source']
): void {
    switch (update.sessionUpdate) {
        case 'user_message_chunk':
        case 'user_message':
            applyUserUpdate(draft, update, source)
            return
        case 'error':
            // The Claude adapter reports a stopped run only through this frame.
            draft.error(asText(update.message) ?? AGENT_STOPPED)
            return
        case 'agent_message_chunk':
            draft.appendChunk(String(update.messageId ?? 'current'), 'assistant', messageText(update))
            return
        case 'agent_message':
            draft.finalizeMessage(String(update.messageId ?? 'current'), messageText(update))
            return
        case 'agent_thought_chunk':
            draft.appendChunk(String(update.messageId ?? 'current-thought'), 'thought', messageText(update))
            return
        case 'tool_call':
            draft.toolCall(update)
            return
        case 'tool_call_update':
            draft.toolCallUpdate(update, notificationError)
            return
        default:
            return
    }
}

function applyFrame(draft: Draft, frame: unknown, context: FrameContext): void {
    const notification = notificationOf(frame)
    if (!notification) {
        return
    }
    if (draft.rebuildPending) {
        // A durable-log replay carries the whole resume chain, so it draws the thread again from the start. A live
        // frame first means the server sent only the new run's events, which follow what the thread already shows.
        if (context.source === 'replay') {
            draft.rebuild()
        } else {
            draft.rebuildPending = false
        }
    }
    const method = notification.method
    const params = asRecord(notification.params) ?? {}
    const notificationError = asText(asRecord(notification.error)?.message)
    switch (method) {
        case 'session/update': {
            const update = asRecord(params.update)
            if (update) {
                applySessionUpdate(draft, update, notificationError, context.source)
            }
            return
        }
        case '_posthog/user_message':
            draft.human(userMessageText(params.content), context.source, true)
            if (Array.isArray(params.content)) {
                for (const block of params.content) {
                    const attachment = isHiddenUserContent(block) ? undefined : userAttachment(block)
                    if (attachment) {
                        draft.noteAttachment(attachment)
                    }
                }
            }
            return
        case '_posthog/turn_complete':
            draft.turnEnd()
            return
        case '_posthog/error':
            draft.error(asText(params.message) ?? notificationError ?? AGENT_ERROR)
            return
        case '_posthog/progress':
            draft.progress(params)
            return
        case '_posthog/status':
            draft.status(params)
            return
        case '_posthog/compact_boundary':
            draft.compactBoundary()
            return
        case '_posthog/conversation_cleared':
            draft.conversationCleared()
            return
        case '_posthog/task_notification':
            draft.taskNotification(params)
            return
        default:
            // `_posthog/console`, `run_started`, `usage_update`, `sdk_session`, `sandbox_output`, `turn_suggestion*`,
            // `session/prompt` and the rest draw nothing.
            return
    }
}

export function sessionThreadReducer(state: SessionThreadState, action: SessionThreadAction): SessionThreadState {
    switch (action.type) {
        case 'frame': {
            if (!notificationOf(action.frame)) {
                return state
            }
            const draft = new Draft(state)
            applyFrame(draft, action.frame, action.context)
            return draft.toState()
        }
        case 'frames': {
            if (action.frames.length === 0) {
                return state
            }
            const draft = new Draft(state)
            for (const { frame, context } of action.frames) {
                applyFrame(draft, frame, context)
            }
            return draft.toState()
        }
        case 'local_user': {
            const text = action.text.trim()
            if (!text) {
                return state
            }
            const draft = new Draft(state)
            draft.localUser(action.id, text, action.echo !== false, action.attachments ?? [])
            return draft.toState()
        }
        case 'withdraw': {
            const draft = new Draft(state)
            draft.withdraw(action.id)
            return draft.toState()
        }
        case 'resuming':
            return { ...state, rebuildPending: true, resumeRun: action.resumeRun ?? state.resumeRun }
        case 'settle': {
            const draft = new Draft(state)
            draft.settle()
            return draft.toState()
        }
        case 'reset':
            return { ...initialSessionThread(action.resumeRun ?? false), counters: state.counters }
    }
}

function runMarker(frame: unknown): string | undefined {
    const notification = notificationOf(frame)
    const params = asRecord(notification?.params)
    if (notification?.method === '_posthog/sdk_session') {
        return asText(params?.taskRunId)
    }
    if (notification?.method === '_posthog/run_started') {
        return asText(params?.runId)
    }
    return undefined
}

/**
 * Tags stored log lines with the run each one belongs to, like the web's `normalizeHistory`. A resume chain's lines
 * before the first run marker have no known run, so they get an empty id and never count as the current run's.
 */
export function historyFrames(entries: readonly unknown[], runId: string, resumed: boolean): SessionFrame[] {
    let sourceRunId = resumed ? '' : runId
    const frames: SessionFrame[] = []
    for (const entry of entries) {
        if (!isRecord(entry)) {
            continue
        }
        sourceRunId = runMarker(entry) ?? sourceRunId
        frames.push({ frame: entry, context: { source: 'replay', sourceRunId } })
    }
    return frames
}
