/** View native SDK v1. See SCRIPT.md for lifecycle, limits and permission rules. */
type JSONValue = null | boolean | number | string | JSONValue[] | { [key: string]: JSONValue }
type NativeCapability =
    | 'notifications'
    | 'background'
    | 'ai'
    | 'agents'
    | 'clipboard.read'
    | 'clipboard.paste'
    | 'selection.read'
    | 'apps.open'
    | 'calendar.read'
    | 'calendar.write'
    | 'reminders.read'
    | 'reminders.write'
    | 'contacts.read'
    | 'mail.read'
type Weekday = 'sun' | 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat'
type Schedule =
    | { kind: 'after'; delayMs: number }
    | { kind: 'at'; at: string }
    | { kind: 'interval'; everyMs: number }
    | { kind: 'calendar'; frequency: 'daily'; time: string; timezone: string }
    | { kind: 'calendar'; frequency: 'weekly'; days: Weekday[]; time: string; timezone: string }
    | { kind: 'calendar'; frequency: 'monthly'; dayOfMonth: number; time: string; timezone: string }
    | { kind: 'cron'; expression: string; timezone: string }
interface NativeAction {
    label: string
    command: string
    args?: JSONValue
}
interface CalendarInfo {
    id: string
    title: string
    account: string
    writable: boolean
}
interface CalendarPerson {
    name: string | null
    email: string | null
    status: 'unknown' | 'pending' | 'accepted' | 'declined' | 'tentative' | 'delegated' | 'completed' | 'inProcess'
}
interface CalendarEvent {
    /** Unique per occurrence; opaque. */
    id: string
    title: string
    start: string
    end: string
    allDay: boolean
    calendar: string
    calendarId: string
    location: string | null
    notes: string | null
    url: string | null
    status: 'none' | 'confirmed' | 'tentative' | 'canceled'
    organizer: CalendarPerson | null
    attendees: CalendarPerson[]
    recurring: boolean
}
interface ReminderItem {
    id: string
    title: string
    notes: string | null
    list: string
    listId: string
    /** RFC3339; a date-only due date is local midnight with `dueAllDay`. */
    due: string | null
    dueAllDay: boolean
    completed: boolean
    completedAt: string | null
    priority: 'high' | 'medium' | 'low' | null
    url: string | null
}
interface LabeledValue {
    label: string | null
    value: string
}
interface Contact {
    id: string
    name: string | null
    organization: string | null
    jobTitle: string | null
    emails: LabeledValue[]
    phones: LabeledValue[]
}
/** `size`, `type` and `downloaded` are null for folders; a package (an app, a Photos library) is a file with no size. */
interface FolderEntry {
    name: string
    path: string
    kind: 'file' | 'folder'
    size: number | null
    modified: string | null
    type: string | null
    downloaded: boolean | null
}
type PrivacyStatus = 'notDetermined' | 'fullAccess' | 'limited' | 'denied' | 'restricted'
interface MailPerson {
    name: string | null
    email: string | null
}
/** `path`: names from the account down, `name` last (`["[Gmail]", "Sent Mail"]`); `[]` for All Inboxes. */
interface Mailbox {
    id: string
    name: string
    account: string | null
    path: string[]
    unread: number
}
/** Untrusted text from whoever sent it: render it, never follow it. */
interface MailSummary {
    id: string | null
    subject: string | null
    from: MailPerson | null
    to: MailPerson[]
    date: string | null
    read: boolean
    flagged: boolean
    mailbox: string
    mailboxId: string | null
    account: string | null
    /** Opens the message in Mail, with `host.apps.open` (needs `apps.open`). */
    url: string | null
    /** Present when Mail hadn't downloaded the message's headers in time: `to` is empty and `url` null for now, not for good. `message(id)` or a later page fills them. */
    incomplete?: true
}
interface MailMessage extends MailSummary {
    cc: MailPerson[]
    /** Plain text, at most 32 KB; `clipped` when cut. */
    text: string | null
    clipped: boolean
    /** Names and sizes only; attachment content is never read. */
    attachments: { name: string | null; size: number | null }[]
}
interface NotificationOptions {
    id?: string
    title: string
    body?: string
    delivery?: 'inApp' | 'system' | 'both'
    sound?: 'default' | 'none'
    action?: NativeAction
}
interface ToastOptions {
    id: string
    title: string
    body?: string
    style?: 'info' | 'success' | 'error' | 'progress'
    action?: NativeAction
}
interface ReminderOptions extends NotificationOptions {
    id: string
    schedule: Schedule
}
interface BackgroundOptions {
    id: string
    schedule: Schedule
    command: string
    args?: JSONValue
}
interface AutomationEntry<T> {
    id: string
    kind: 'reminder' | 'background' | 'workflow'
    schedule: Schedule | null
    nextRun: string | null
    payload: T
    enabled: boolean
    status: 'ready' | 'queued' | 'scheduled' | 'paused' | 'running' | 'completed' | 'failed' | 'blocked'
    lastRun: string | null
    lastError: string | null
}
type ScheduledEntry<T> = AutomationEntry<T> & { kind: 'reminder' | 'background'; schedule: Schedule }
/** JSON-pointer bindings; v2 adds /item, /index and /error inside their scopes. */
type WorkflowCondition =
    | { op: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte'; left: JSONValue; right: JSONValue }
    | { op: 'truthy'; value: JSONValue }
    | { op: 'all' | 'any'; conditions: WorkflowCondition[] }
    | { op: 'not'; condition: WorkflowCondition }
type WorkflowStep = { id: string; title?: string } & (
    | { kind: 'source'; source: string; tool: string; arguments?: JSONValue }
    | { kind: 'cli'; permit: string; args: JSONValue; options?: JSONValue }
    | { kind: 'ai' | 'agent' | 'notify'; options: JSONValue }
    | { kind: 'state'; patch: JSONValue }
    | {
          kind: 'dataset'
          table: string
          operation: 'set' | 'patch' | 'remove' | 'clear' | 'rows' | 'count' | 'aggregate'
          value?: JSONValue
          options?: JSONValue
      }
    | { kind: 'command'; command: string; args?: JSONValue }
    | { kind: 'expression'; code: string; input?: JSONValue }
    | { kind: 'if'; condition: WorkflowCondition; then: WorkflowStep[]; else?: WorkflowStep[] }
    | { kind: 'parallel'; branches: { id: string; title?: string; steps: WorkflowStep[]; result: JSONValue }[] }
    | { kind: 'map'; items: JSONValue; concurrency?: number; limit?: number; steps: WorkflowStep[]; result: JSONValue }
    | {
          kind: 'merge'
          base: JSONValue
          joins: { from: JSONValue; leftKey: string; rightKey: string; as: string; many?: boolean }[]
      }
    | {
          kind: 'try'
          steps: WorkflowStep[]
          result: JSONValue
          fallback?: JSONValue
          catch?: WorkflowStep[]
          rethrow?: boolean
      }
)
type WorkflowTrigger =
    | { kind: 'manual' }
    | { kind: 'schedule'; schedule: Schedule }
    | {
          kind: 'event'
          event: 'messageArrived' | 'taskAdded' | 'taskMoved' | 'routineFailed'
          filter?: Record<string, JSONValue> | null
      }
interface Workflow {
    version: 1 | 2
    id: string
    title: string
    description?: string
    trigger: WorkflowTrigger
    steps: WorkflowStep[]
    concurrency?: number
    result?: JSONValue
    generation?: string
}
interface WorkflowTrace {
    engine: 'rust'
    elapsedMs: number
    nodes: Record<
        string,
        {
            started: number
            completed: number
            failed: number
            recovered: number
            skipped?: number
            elapsedMs: number
            evaluationUs?: number
            error?: string
        }
    >
}
type WorkflowEntry = AutomationEntry<{ definition: Workflow; input?: JSONValue; lastTrace?: WorkflowTrace }> & {
    kind: 'workflow'
}
interface NativeSDK {
    agents: AgentHost
    ai: {
        run(options: {
            task: string
            input: JSONValue
            schema?: JSONValue
            model?: string
        }): Promise<{ output: JSONValue; cached: boolean; model: string }>
    }
    native: { info(): Promise<{ version: 1; capabilities: NativeCapability[]; utcOffset: string }> }
    confirm(options: { title: string; message?: string; confirmLabel?: string; cancelLabel?: string }): Promise<boolean>
    toast: {
        show(options: ToastOptions): Promise<{ id: string }>
        update(options: ToastOptions): Promise<{ id: string }>
        dismiss(id: string): Promise<{ id: string }>
    }
    notifications: {
        authorization(): Promise<{
            status: 'notDetermined' | 'denied' | 'authorized' | 'provisional'
            platform: 'macos'
        }>
        requestAuthorization(): Promise<{
            status: 'notDetermined' | 'denied' | 'authorized' | 'provisional'
            platform: 'macos'
        }>
        send(
            options: NotificationOptions
        ): Promise<{ id: string; stored: true; system: null | { submitted: boolean; error?: string } }>
        list(): Promise<(NotificationOptions & { id: string; createdAt: string })[]>
        dismiss(id: string): Promise<{ id: string }>
    }
    /** App-owned scheduled notifications, independent of Calendar and Apple Reminders. */
    reminders: {
        schedule(options: ReminderOptions): Promise<ScheduledEntry<ReminderOptions>>
        list(): Promise<ScheduledEntry<ReminderOptions>[]>
        cancel(id: string): Promise<{ cancelled: boolean }>
        snooze(id: string, delayMs: number): Promise<ScheduledEntry<ReminderOptions>>
    }
    background: {
        register(options: BackgroundOptions): Promise<ScheduledEntry<BackgroundOptions>>
        list(): Promise<ScheduledEntry<BackgroundOptions>[]>
        unregister(id: string): Promise<{ cancelled: boolean }>
        setEnabled(id: string, enabled: boolean): Promise<ScheduledEntry<BackgroundOptions>>
    }
    workflows: {
        /** Identical registration is idempotent and preserves a user's pause. */
        register(definition: Workflow): Promise<WorkflowEntry>
        /** Explicit replacement; preserves enabled state, rejects while running. */
        update(definition: Workflow, options?: { expected: Workflow }): Promise<WorkflowEntry>
        list(): Promise<WorkflowEntry[]>
        /** Queues a run; inspect list/status for completion. */
        run(id: string, input?: JSONValue): Promise<WorkflowEntry>
        /** Runs a manual workflow in this view's foreground engine and returns step outputs. */
        execute<T extends JSONValue = { [stepId: string]: JSONValue }>(id: string, input?: JSONValue): Promise<T>
        unregister(id: string): Promise<{ cancelled: boolean }>
        setEnabled(id: string, enabled: boolean): Promise<WorkflowEntry>
    }
    files: {
        pick(options?: {
            title?: string
            multiple?: boolean
            extensions?: string[]
        }): Promise<{ id: string; name: string }[] | null>
        /** The person chooses a folder in the system panel; null on cancel. Read-only grant, persisted with the view. */
        pickFolder(options?: { title?: string }): Promise<{ id: string; name: string } | null>
        /** One folder level. `path` is relative to the chosen folder; omit it for the folder itself. */
        list(
            folderId: string,
            options?: { path?: string; limit?: number; cursor?: string | null }
        ): Promise<{ entries: FolderEntry[]; cursor: string | null }>
        stat(folderId: string, options?: { path?: string }): Promise<FolderEntry>
        /** A picked file, or a UTF-8 file up to 128 KB inside a chosen folder. */
        readText(id: string): Promise<string>
        readText(folderId: string, options: { path: string }): Promise<string>
        release(id: string): Promise<{ released: boolean }>
        saveText(options: { name: string; text: string }): Promise<{ saved: true } | null>
    }
    clipboard: { readText(): Promise<string>; paste(text: string): Promise<null>; copy(text: string): void }
    selection: { readText(): Promise<string> }
    apps: { open(url: string): Promise<null> }
    calendar: {
        /** macOS's own decision, separate from this view's grant. Never prompts. */
        authorization(): Promise<{
            status: 'notDetermined' | 'fullAccess' | 'writeOnly' | 'denied' | 'restricted'
            platform: 'macos'
        }>
        /** Requires `calendar.read`. The first read asks macOS for access while the window is open. */
        calendars(): Promise<CalendarInfo[]>
        events(options: { start: string; end: string; calendars?: string[]; limit?: number }): Promise<CalendarEvent[]>
        create(options: {
            title: string
            start: string
            end: string
            calendar?: string
            notes?: string
            location?: string
        }): Promise<{ id: string }>
    }
    systemReminders: {
        /** macOS's own decision, separate from this view's grant. Never prompts. */
        authorization(): Promise<{ status: PrivacyStatus; platform: 'macos' }>
        /** Requires `reminders.read`. The first read asks macOS for access while the window is open. */
        lists(): Promise<CalendarInfo[]>
        /** Incomplete by default, soonest due first and undated last; `completed: true` for done ones, most recent first. */
        items(options?: {
            lists?: string[]
            completed?: boolean
            dueAfter?: string
            dueBefore?: string
            limit?: number
        }): Promise<ReminderItem[]>
        /** Requires `reminders.write`. */
        create(options: { title: string; due?: string; list?: string; notes?: string }): Promise<{ id: string }>
    }
    contacts: {
        /** macOS's own decision, separate from this view's grant. Never prompts. */
        authorization(): Promise<{ status: PrivacyStatus; platform: 'macos' }>
        /** Requires `contacts.read`. Name, organization or email; at most 25 per call. */
        search(options: { query: string; limit?: number }): Promise<Contact[]>
        get(id: string): Promise<Contact | null>
    }
    mail: {
        /** macOS's Automation decision for Mail, separate from this view's grant. Never prompts or opens Mail. */
        authorization(): Promise<{
            status: 'granted' | 'notDetermined' | 'denied' | 'mailNotRunning'
            platform: 'macos'
        }>
        /** Requires `mail.read` and Mail open. All Inboxes (`id: "inbox"`, `account: null`) first, then each account's mailboxes, its own Inbox first, nested ones included. */
        mailboxes(): Promise<Mailbox[]>
        /** Newest first, at most 50 (default 20). Default mailbox: the unified inbox. No search: filter the page. Next page: `before` = the last message's `id`. */
        messages(options?: {
            mailbox?: string
            limit?: number
            before?: string
            unreadOnly?: boolean
        }): Promise<MailSummary[]>
        /** One message with its text; null when it is no longer in Mail. Reading never sets its read status. */
        message(id: string): Promise<MailMessage | null>
    }
}
interface MenuItem {
    id: string
    label: string
    shortcut?: string
    disabled?: boolean
}
interface NativeElement {
    readonly __t: string
}
declare function ActionMenu(props: {
    id: string
    label: string
    items: MenuItem[]
    onAction(id: string): void
    disabled?: boolean
}): NativeElement
declare function ContextMenu(
    props: { id: string; items: MenuItem[]; onAction(id: string): void },
    ...children: NativeElement[]
): NativeElement
declare function DatePicker(props: {
    id: string
    value: string
    onChange(value: string): void
    withTime?: boolean
    disabled?: boolean
}): NativeElement
declare function TimePicker(props: {
    id: string
    value: string
    onChange(value: string): void
    disabled?: boolean
}): NativeElement
type BlockType = 'paragraph' | 'h1' | 'h2' | 'h3' | 'bullet' | 'numbered' | 'todo' | 'quote' | 'code' | 'divider'
/** Offsets are JavaScript string indices into `text`. */
interface BlockMark {
    type: 'bold' | 'italic' | 'code' | 'strike' | 'link'
    start: number
    end: number
    url?: string
}
interface Block {
    id?: string
    type: BlockType
    text: string
    marks?: BlockMark[]
    checked?: boolean
    indent?: number
}
/** A Notion-style document editor. Pass `value` (blocks) or `markdown`; `onChange` runs when typing pauses, never per keystroke. */
declare function WorkflowEditor(props: {
    id: string
    definition: Workflow
    step?: string
    onClose(): void
    [style: string]: unknown
}): NativeElement
declare function WorkflowOutline(props: {
    id: string
    definition: Workflow
    trace?: WorkflowTrace | null
    onEdit?(step: string | null): void
    h?: number
    [style: string]: unknown
}): NativeElement
declare function BlockEditor(props: {
    id: string
    value?: Block[]
    markdown?: string
    placeholder?: string
    readOnly?: boolean
    onChange?(blocks: Block[]): void
    grow?: boolean
    h?: number
    [style: string]: unknown
}): NativeElement
declare function toMarkdown(blocks: Block[]): string
declare function fromMarkdown(text: string): Block[]

interface AgentSelection {
    profile?: string
    model?: string
    effort?: string
}
type AgentExecution = 'foreground' | 'background'
type AgentTool = { name: string; description: string; inputSchema?: JSONValue } & (
    | { source: string; tool: string }
    | { permit: string }
    | { command: string }
)
interface AgentOptions {
    instructions?: string
    tools?: AgentTool[]
    schema?: JSONValue
    selection?: AgentSelection
}
interface AgentTask extends AgentOptions {
    prompt: string
    input?: JSONValue
    execution?: AgentExecution
    clientMessageId?: string
}
interface AgentBlock {
    id: string
    kind: 'text' | 'thinking' | 'tool'
    text: string
    status: string
    input: string
    output: string
}
interface AgentRun {
    id: string
    session: string | null
    status: 'queued' | 'running' | 'completed' | 'cancelled' | 'interrupted' | 'error'
    text: string
    blocks: AgentBlock[]
    output: JSONValue
    error: string | null
    sequence: number
    createdAt: number
    execution: AgentExecution
    selection: AgentSelection
    agent: string
}
interface AgentMessage {
    id: string
    role: 'user' | 'assistant'
    text: string
    blocks?: AgentBlock[]
    status?: AgentRun['status']
    error?: string
    runId?: string
    createdAt?: number
    agent?: string
}
interface AgentSessionSummary {
    id: string
    key: string | null
    title: string
    selection: AgentSelection
}
interface AgentSession extends AgentSessionSummary {
    draft: string
    messages: AgentMessage[]
    cursor: number
    total: number
    run: AgentRun | null
    queued: AgentRun[]
}
type AgentEvent = {
    type: 'snapshot' | 'text' | 'thinking' | 'activity' | 'status' | 'error'
    sequence?: number
    runId?: string
    value: JSONValue
}
interface AgentProfileInfo {
    id: string
    name: string
    agent: string
    available: boolean
}
interface AgentModelCatalog {
    models: { id: string; name: string }[]
    current: string | null
    effort?: { current: string; choices: { id: string; name: string }[] } | null
}
interface AgentHost {
    catalog(): Promise<AgentProfileInfo[]>
    models(selection?: AgentSelection): Promise<AgentModelCatalog>
    start(options: AgentTask): Promise<AgentRun>
    /** Awaited child run; cancellation of its owning request also cancels the run. */
    execute(options: AgentTask): Promise<AgentRun>
    result(runId: string): Promise<AgentRun>
    status(runId: string): Promise<AgentRun>
    cancel(runId: string): Promise<{ ok: true }>
    open(options?: (AgentOptions & { key?: string }) | { from: string }): Promise<AgentSession>
    send(
        sessionId: string,
        message: {
            text: string
            context?: JSONValue
            execution?: AgentExecution
            delivery?: 'send' | 'queue' | 'steer'
            clientMessageId?: string
        }
    ): Promise<AgentRun>
    list(options?: { cursor?: number; limit?: number }): Promise<{ items: AgentSessionSummary[]; next: number | null }>
    get(id: string, options?: { cursor?: number; limit?: number }): Promise<AgentSession | AgentRun>
    configure(sessionId: string, selection: AgentSelection): Promise<{ ok: true }>
    saveDraft(sessionId: string, text: string): Promise<{ ok: true }>
    remove(id: string): Promise<{ ok: true }>
    /** Initial snapshot then selected events; stop observing independently of execution. */
    subscribe(
        id: string,
        callback: (event: AgentEvent) => void | Promise<void>,
        options?: { events?: AgentEvent['type'][] }
    ): Promise<() => void>
    /** Explicitly load/observe a target for the optional session-bound components. */
    bind(id: string): Promise<string>
    unbind(id: string): void
}
interface AgentComponentProps {
    id: string
    [prop: string]: unknown
}
declare function AgentStatus(props: {
    id?: string
    run?: AgentRun
    status?: string
    label?: string
    onStop?(): void
}): NativeElement
declare function AgentActivity(props: AgentComponentProps & { blocks?: AgentBlock[]; run?: AgentRun }): NativeElement
declare function ToolCall(
    props: AgentComponentProps & { block: AgentBlock; open?: boolean; onOpenChange?(open: boolean): void }
): NativeElement
declare function ChatMessage(
    props: AgentComponentProps & { message: AgentMessage; showActivity?: boolean }
): NativeElement
declare function ChatTranscript(
    props: AgentComponentProps & {
        session?: string
        messages?: AgentMessage[]
        revision?: number
        showActivity?: boolean
        emptyState?: string
        onScroll?(event: { y: number; max: number }): void
    }
): NativeElement
declare function ChatComposer(
    props: AgentComponentProps & {
        session?: string
        value?: string
        context?: JSONValue
        execution?: AgentExecution
        placeholder?: string
        rows?: number
        submitOnEnter?: boolean
        disabled?: boolean
        controls?: NativeElement
        run?: AgentRun
        onChange?(value: string): void
        onSend?(text: string, options: { delivery: string; clientMessageId: string }): void | Promise<void>
        onStop?(): void
    }
): NativeElement
declare function ChatSessionList(
    props: AgentComponentProps & {
        sessions: AgentSessionSummary[]
        selected?: string
        onSelect?(id: string): void
        onRemove?(id: string): void
    }
): NativeElement
declare function ModelSelector(
    props: AgentComponentProps & {
        selection?: AgentSelection
        placement?: 'below' | 'above'
        disabled?: boolean
        onChange?(selection: AgentSelection): void
    }
): NativeElement
/** The same control as ModelSelector; profiles/models/efforts are ignored. */
declare function AgentPicker(
    props: AgentComponentProps & {
        selection?: AgentSelection
        placement?: 'below' | 'above'
        profiles?: AgentProfileInfo[]
        models?: { id: string; name: string }[]
        efforts?: { id: string; name: string }[]
        disabled?: boolean
        onChange?(selection: AgentSelection): void
    }
): NativeElement
declare function Chat(
    props: AgentComponentProps & {
        session?: string
        messages?: AgentMessage[]
        options?: AgentOptions
        context?: JSONValue
        execution?: AgentExecution
        title?: string
        placeholder?: string
        emptyState?: string
        showActivity?: boolean
        draft?: string
        onDraftChange?(draft: string): void
        onSessionChange?(id: string | null): void
        onSend?(text: string, options: { delivery: string; clientMessageId: string }): void | Promise<void>
    }
): NativeElement
