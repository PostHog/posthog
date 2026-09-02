/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `draft` - draft
 * * `active` - active
 * * `done` - done
 */
export type DocStatusEnumApi = (typeof DocStatusEnumApi)[keyof typeof DocStatusEnumApi]

export const DocStatusEnumApi = {
    Draft: 'draft',
    Active: 'active',
    Done: 'done',
} as const

/**
 * * `page` - page
 * * `context` - context
 */
export type DocKindEnumApi = (typeof DocKindEnumApi)[keyof typeof DocKindEnumApi]

export const DocKindEnumApi = {
    Page: 'page',
    Context: 'context',
} as const

/**
 * Who did something, as much of a person as a doc surface needs.
 */
export interface DocPersonApi {
    /** Numeric id of the person. */
    id: number
    /** Stable id of the person. */
    uuid: string
    /** First name. */
    first_name: string
    /** Last name. */
    last_name: string
    /** Email address. */
    email: string
}

/**
 * A doc without its body. Used for the tab row and the space home list.
 */
export interface DocSummaryApi {
    /** Unique id of the doc. */
    id: string
    /** The space (channel) the doc belongs to. */
    channel_id: string
    /** Title of the doc, shown on its tab. */
    title: string
    /** Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.
     *
     * * `draft` - draft
     * * `active` - active
     * * `done` - done */
    status: DocStatusEnumApi
    /** page: a page the space writes. context: the one doc that is the space's context notes.
     *
     * * `page` - page
     * * `context` - context */
    kind: DocKindEnumApi
    /** Order of the doc in the space's tab row, lowest first. */
    position: number
    /** Collab version of the stored body. Increases by one for every accepted step. */
    version: number
    /** The person who created the doc. */
    created_by: DocPersonApi | null
    /** When the doc was created. */
    created_at: string
    /** When the doc was last written to. */
    updated_at: string
    /** The first words of the page, for a list. Empty outside the space home. */
    excerpt: string
    /** Threads on the page not yet marked handled. */
    open_thread_count: number
    /** Hypotheses on the page still under watch. */
    watch_count: number
}

/**
 * * `blank` - blank
 * * `notes` - notes
 */
export type TemplateEnumApi = (typeof TemplateEnumApi)[keyof typeof TemplateEnumApi]

export const TemplateEnumApi = {
    Blank: 'blank',
    Notes: 'notes',
} as const

/**
 * What a new doc needs.
 */
export interface DocCreateApi {
    /** The space (channel) the doc belongs to. */
    channel: string
    /**
     * Title of the doc. Defaults to the template name.
     * @maxLength 400
     */
    title?: string
    /** Starting content: 'blank' is an empty page, 'notes' has headings for notes from a call.
     *
     * * `blank` - blank
     * * `notes` - notes */
    template?: TemplateEnumApi
}

/**
 * The doc body as a ProseMirror document.
 * @nullable
 */
export type DocApiContent = { [key: string]: unknown } | null

/**
 * A doc with its body.
 */
export interface DocApi {
    /** Unique id of the doc. */
    id: string
    /** The space (channel) the doc belongs to. */
    channel_id: string
    /** Title of the doc, shown on its tab. */
    title: string
    /** Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.
     *
     * * `draft` - draft
     * * `active` - active
     * * `done` - done */
    status: DocStatusEnumApi
    /** page: a page the space writes. context: the one doc that is the space's context notes.
     *
     * * `page` - page
     * * `context` - context */
    kind: DocKindEnumApi
    /** Order of the doc in the space's tab row, lowest first. */
    position: number
    /** Collab version of the stored body. Increases by one for every accepted step. */
    version: number
    /** The person who created the doc. */
    created_by: DocPersonApi | null
    /** When the doc was created. */
    created_at: string
    /** When the doc was last written to. */
    updated_at: string
    /** The first words of the page, for a list. Empty outside the space home. */
    excerpt: string
    /** Threads on the page not yet marked handled. */
    open_thread_count: number
    /** Hypotheses on the page still under watch. */
    watch_count: number
    /**
     * The doc body as a ProseMirror document.
     * @nullable
     */
    content: DocApiContent
    /** Plain-text mirror of the body, written on every save. */
    text_content: string
}

/**
 * The parts of a doc a person can change outside the editor.
 */
export interface PatchedDocUpdateApi {
    /**
     * New title for the doc.
     * @maxLength 400
     */
    title?: string
    /** Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.
     *
     * * `draft` - draft
     * * `active` - active
     * * `done` - done */
    status?: DocStatusEnumApi
}

/**
 * A caret ping, broadcast to everyone else in the doc.
 */
export interface DocPresenceApi {
    /**
     * Id of the editing client, unique per open tab.
     * @maxLength 64
     */
    client_id: string
    /** The collab version the caret position is relative to. */
    version: number
    /** Caret position as {'anchor': int, 'head': int}. */
    cursor: unknown
}

/**
 * The whole document after the steps are applied.
 */
export type DocCollabSaveApiContent = { [key: string]: unknown }

/**
 * One batch of prosemirror-collab steps, with the document they produce.
 */
export interface DocCollabSaveApi {
    /**
     * Id of the editing client, unique per open tab.
     * @maxLength 64
     */
    client_id: string
    /** The steps to append, in order. */
    steps: unknown[]
    /** The collab version the submitted steps are based on. */
    version: number
    /** The whole document after the steps are applied. */
    content: DocCollabSaveApiContent
    /** Plain-text mirror of the body. */
    text_content?: string
    /**
     * Title to store with this save.
     * @maxLength 400
     */
    title?: string
    /**
     * The caller's caret position, broadcast with the steps.
     * @nullable
     */
    cursor_head?: number | null
}

/**
 * * `conflict` - conflict
 * * `stale` - stale
 */
export type DocCollabConflictCodeEnumApi =
    (typeof DocCollabConflictCodeEnumApi)[keyof typeof DocCollabConflictCodeEnumApi]

export const DocCollabConflictCodeEnumApi = {
    Conflict: 'conflict',
    Stale: 'stale',
} as const

/**
 * The save was rejected because other steps landed first.
 */
export interface DocCollabConflictApi {
    /** 'conflict' means the missed steps are included. 'stale' means the client must reload the doc.
     *
     * * `conflict` - conflict
     * * `stale` - stale */
    code: DocCollabConflictCodeEnumApi
    /** The steps the client missed, in order. */
    steps?: unknown[]
    /** Authors of the missed steps, index-aligned with 'steps'. */
    client_ids?: string[]
    /** The current collab version of the doc. */
    version: number
}

/**
 * * `human` - human
 * * `agent` - agent
 * * `system` - system
 */
export type AuthorKindEnumApi = (typeof AuthorKindEnumApi)[keyof typeof AuthorKindEnumApi]

export const AuthorKindEnumApi = {
    Human: 'human',
    Agent: 'agent',
    System: 'system',
} as const

/**
 * * `brief` - brief
 * * `check` - check
 * * `moved` - moved
 * * `stale` - stale
 * * `report` - report
 * * `verdict` - verdict
 * * `scout` - scout
 * * `stopped` - stopped
 * * `paused` - paused
 * * `resumed` - resumed
 */
export type DocWatchEventEnumApi = (typeof DocWatchEventEnumApi)[keyof typeof DocWatchEventEnumApi]

export const DocWatchEventEnumApi = {
    Brief: 'brief',
    Check: 'check',
    Moved: 'moved',
    Stale: 'stale',
    Report: 'report',
    Verdict: 'verdict',
    Scout: 'scout',
    Stopped: 'stopped',
    Paused: 'paused',
    Resumed: 'resumed',
} as const

/**
 * * `text` - text
 * * `data` - data
 * * `watch` - watch
 */
export type DocThreadKindEnumApi = (typeof DocThreadKindEnumApi)[keyof typeof DocThreadKindEnumApi]

export const DocThreadKindEnumApi = {
    Text: 'text',
    Data: 'data',
    Watch: 'watch',
} as const

/**
 * * `active` - active
 * * `paused` - paused
 * * `stopped` - stopped
 */
export type DocWatchStatusEnumApi = (typeof DocWatchStatusEnumApi)[keyof typeof DocWatchStatusEnumApi]

export const DocWatchStatusEnumApi = {
    Active: 'active',
    Paused: 'paused',
    Stopped: 'stopped',
} as const

/**
 * * `section_removed` - section_removed
 * * `page_done` - page_done
 * * `page_deleted` - page_deleted
 * * `handled` - handled
 * * `person` - person
 * * `verdict` - verdict
 */
export type DocWatchStopReasonEnumApi = (typeof DocWatchStopReasonEnumApi)[keyof typeof DocWatchStopReasonEnumApi]

export const DocWatchStopReasonEnumApi = {
    SectionRemoved: 'section_removed',
    PageDone: 'page_done',
    PageDeleted: 'page_deleted',
    Handled: 'handled',
    Person: 'person',
    Verdict: 'verdict',
} as const

/**
 * * `pending` - pending
 * * `holding` - holding
 * * `moved` - moved
 * * `confirmed` - confirmed
 * * `refuted` - refuted
 * * `stale` - stale
 */
export type DocWatchVerdictEnumApi = (typeof DocWatchVerdictEnumApi)[keyof typeof DocWatchVerdictEnumApi]

export const DocWatchVerdictEnumApi = {
    Pending: 'pending',
    Holding: 'holding',
    Moved: 'moved',
    Confirmed: 'confirmed',
    Refuted: 'refuted',
    Stale: 'stale',
} as const

/**
 * * `agent` - agent
 * * `person` - person
 * * `page` - page
 */
export type DocWatchActorEnumApi = (typeof DocWatchActorEnumApi)[keyof typeof DocWatchActorEnumApi]

export const DocWatchActorEnumApi = {
    Agent: 'agent',
    Person: 'person',
    Page: 'page',
} as const

export interface WatchVerdictApi {
    /** pending: no brief yet. holding: the evidence stands. moved: a number left its baseline. confirmed or refuted: decided, and the watch ended. stale: the checks could not run.
     *
     * * `pending` - pending
     * * `holding` - holding
     * * `moved` - moved
     * * `confirmed` - confirmed
     * * `refuted` - refuted
     * * `stale` - stale */
    verdict: DocWatchVerdictEnumApi
    /** Why, in one line. */
    reason: string
    /** agent, person, or page for a derived verdict.
     *
     * * `agent` - agent
     * * `person` - person
     * * `page` - page */
    by: DocWatchActorEnumApi
    /**
     * When the verdict was set.
     * @nullable
     */
    at: string | null
}

/**
 * * `number` - number
 * * `series` - series
 * * `table` - table
 */
export type DocDataShapeEnumApi = (typeof DocDataShapeEnumApi)[keyof typeof DocDataShapeEnumApi]

export const DocDataShapeEnumApi = {
    Number: 'number',
    Series: 'series',
    Table: 'table',
} as const

/**
 * One number the claim stands on, and where it is against its baseline.
 */
export interface WatchEvidenceApi {
    /** What the number counts. */
    label: string
    /** The HogQL SELECT the page reruns. */
    query: string
    /** number, or series for a trend.
     *
     * * `number` - number
     * * `series` - series
     * * `table` - table */
    shape: DocDataShapeEnumApi
    /**
     * The value when the brief landed.
     * @nullable
     */
    baseline: number | null
    /**
     * The value at the last check.
     * @nullable
     */
    value: number | null
    /**
     * When it was last checked.
     * @nullable
     */
    checked_at: string | null
    /**
     * Why the last check did not run, or null.
     * @nullable
     */
    error: string | null
    /** [time, value] pairs, oldest first, at most sixty. */
    history: unknown[][]
    /** True when the value left its baseline by a fifth or more. */
    moved: boolean
}

/**
 * What the agent compiled the claim into.
 */
export interface WatchBriefApi {
    /** The claim in one sentence. */
    claim: string
    /** What would confirm it. */
    confirms: string
    /** What would refute it. */
    refutes: string
    /** The numbers the page rechecks daily. */
    evidence: WatchEvidenceApi[]
    /** What the scout follows: events, flags, errors, replays. */
    signals: string[]
    /**
     * When the brief landed.
     * @nullable
     */
    submitted_at: string | null
}

export interface WatchScoutApi {
    /** The scout config that follows the signals. */
    config_id: string
    /** The scout's skill name. */
    skill_name: string
}

/**
 * The watch on a thread: whether it runs, what it stands on, and where the claim stands.
 */
export interface DocWatchApi {
    /** active: checks and the scout run. paused: the page is done. stopped: final.
     *
     * * `active` - active
     * * `paused` - paused
     * * `stopped` - stopped */
    status: DocWatchStatusEnumApi
    /** Why the watch stopped or paused, or null while it runs.
     *
     * * `section_removed` - section_removed
     * * `page_done` - page_done
     * * `page_deleted` - page_deleted
     * * `handled` - handled
     * * `person` - person
     * * `verdict` - verdict */
    stopped_reason: DocWatchStopReasonEnumApi | null
    /** Where the claim stands. */
    verdict: WatchVerdictApi
    /** The brief, or null until the agent hands it in. */
    brief: WatchBriefApi | null
    /** The scout, or null when none follows the signals. */
    scout: WatchScoutApi | null
    /**
     * Why the scout could not start, or null.
     * @nullable
     */
    scout_error: string | null
    /**
     * When the evidence is checked next.
     * @nullable
     */
    next_check_at: string | null
    /**
     * When the evidence was last checked.
     * @nullable
     */
    checked_at: string | null
    /** True for a watch on a number already on the page. */
    evidence_only: boolean
}

/**
 * The query behind a data point.
 */
export interface DataAnswerApi {
    /** A HogQL SELECT. The page runs it on every read. */
    query: string
    /** What the data point measures, in a few words. */
    label: string
    /** A caveat for the reader, or empty. */
    note: string
    /** number: one cell, shown inline. series: dates and numbers, shown as a sparkline. table: anything else, shown as a chart block.
     *
     * * `number` - number
     * * `series` - series
     * * `table` - table */
    shape: DocDataShapeEnumApi
    /**
     * The run that submitted it.
     * @nullable
     */
    run_id: string | null
    /**
     * When it was last submitted.
     * @nullable
     */
    updated_at: string | null
}

/**
 * One message in a thread.
 */
export interface DiscussionPostApi {
    /** Unique id of the message. */
    id: string
    /** What was written. */
    content: string
    /** The person who wrote it. Null for the agent and for system lines. */
    created_by: DocPersonApi | null
    /** When it was written. */
    created_at: string
    /** human: a person. agent: the agent's turn. system: a one-line note the page wrote.
     *
     * * `human` - human
     * * `agent` - agent
     * * `system` - system */
    author_kind: AuthorKindEnumApi
    /** Whether this post reached the agent's run. */
    sent_to_agent: boolean
    /** On a post a watch wrote: what it stands for, so a timeline reads it without parsing words.
     *
     * * `brief` - brief
     * * `check` - check
     * * `moved` - moved
     * * `stale` - stale
     * * `report` - report
     * * `verdict` - verdict
     * * `scout` - scout
     * * `stopped` - stopped
     * * `paused` - paused
     * * `resumed` - resumed */
    event?: DocWatchEventEnumApi | null
}

/**
 * A thread anchored to a phrase or a data point in the doc, with its posts.
 */
export interface DiscussionThreadApi {
    /** Unique id of the message. */
    id: string
    /** What was written. */
    content: string
    /** The person who wrote it. Null for the agent and for system lines. */
    created_by: DocPersonApi | null
    /** When it was written. */
    created_at: string
    /** human: a person. agent: the agent's turn. system: a one-line note the page wrote.
     *
     * * `human` - human
     * * `agent` - agent
     * * `system` - system */
    author_kind: AuthorKindEnumApi
    /** Whether this post reached the agent's run. */
    sent_to_agent: boolean
    /** On a post a watch wrote: what it stands for, so a timeline reads it without parsing words.
     *
     * * `brief` - brief
     * * `check` - check
     * * `moved` - moved
     * * `stale` - stale
     * * `report` - report
     * * `verdict` - verdict
     * * `scout` - scout
     * * `stopped` - stopped
     * * `paused` - paused
     * * `resumed` - resumed */
    event?: DocWatchEventEnumApi | null
    /** Key that ties this thread to a mark or an inline request in the doc body. */
    anchor_key: string
    /** The phrase or question the thread was started from. */
    anchor_text: string
    /** Whether the thread is marked as handled. */
    resolved: boolean
    /** text: started from a phrase. data: the thread behind a data point the page asked for. watch: a hypothesis the page keeps watching.
     *
     * * `text` - text
     * * `data` - data
     * * `watch` - watch */
    kind: DocThreadKindEnumApi
    /**
     * The agent task this thread talks to. Set by the client that started the run.
     * @nullable
     */
    task_id: string | null
    /** The watch, on a watch thread. */
    watch: DocWatchApi | null
    /** The query a data thread ended with, or null. */
    answer: DataAnswerApi | null
    /** Posts after the first, oldest first. */
    replies: DiscussionPostApi[]
}

export interface WatchEvidenceInputApi {
    /**
     * What the number counts.
     * @maxLength 120
     */
    label: string
    /** One HogQL SELECT: one number, or a date and a number per row. */
    query: string
}

/**
 * What a new thread needs.
 */
export interface DiscussionCreateApi {
    /** The first message. */
    content: string
    /**
     * Key the client also writes onto the mark around the selected phrase, or the request id.
     * @maxLength 64
     */
    anchor_key: string
    /**
     * The selected phrase or the question, quoted in the panel.
     * @maxLength 280
     */
    anchor_text: string
    /** text for a phrase, data for a data point the page asked for, watch for a hypothesis to keep watching.
     *
     * * `text` - text
     * * `data` - data
     * * `watch` - watch */
    kind?: DocThreadKindEnumApi
    /**
     * The agent task this thread talks to. Set by the client that started the run.
     * @maxLength 64
     * @nullable
     */
    task_id?: string | null
    /** For a watch on a number already on the page: its query. No agent and no scout are involved. */
    evidence?: WatchEvidenceInputApi[]
    /** True when the post tags the agent. With a live run the text is forwarded into it. */
    send_to_agent?: boolean
}

/**
 * * `not_requested` - not_requested
 * * `sent` - sent
 * * `no_run` - no_run
 * * `failed` - failed
 */
export type DeliveryEnumApi = (typeof DeliveryEnumApi)[keyof typeof DeliveryEnumApi]

export const DeliveryEnumApi = {
    NotRequested: 'not_requested',
    Sent: 'sent',
    NoRun: 'no_run',
    Failed: 'failed',
} as const

/**
 * The thread after a post, and what happened to the post if it was for the agent.
 */
export interface DiscussionReplyResultApi {
    /** Unique id of the message. */
    id: string
    /** What was written. */
    content: string
    /** The person who wrote it. Null for the agent and for system lines. */
    created_by: DocPersonApi | null
    /** When it was written. */
    created_at: string
    /** human: a person. agent: the agent's turn. system: a one-line note the page wrote.
     *
     * * `human` - human
     * * `agent` - agent
     * * `system` - system */
    author_kind: AuthorKindEnumApi
    /** Whether this post reached the agent's run. */
    sent_to_agent: boolean
    /** On a post a watch wrote: what it stands for, so a timeline reads it without parsing words.
     *
     * * `brief` - brief
     * * `check` - check
     * * `moved` - moved
     * * `stale` - stale
     * * `report` - report
     * * `verdict` - verdict
     * * `scout` - scout
     * * `stopped` - stopped
     * * `paused` - paused
     * * `resumed` - resumed */
    event?: DocWatchEventEnumApi | null
    /** Key that ties this thread to a mark or an inline request in the doc body. */
    anchor_key: string
    /** The phrase or question the thread was started from. */
    anchor_text: string
    /** Whether the thread is marked as handled. */
    resolved: boolean
    /** text: started from a phrase. data: the thread behind a data point the page asked for. watch: a hypothesis the page keeps watching.
     *
     * * `text` - text
     * * `data` - data
     * * `watch` - watch */
    kind: DocThreadKindEnumApi
    /**
     * The agent task this thread talks to. Set by the client that started the run.
     * @nullable
     */
    task_id: string | null
    /** The watch, on a watch thread. */
    watch: DocWatchApi | null
    /** The query a data thread ended with, or null. */
    answer: DataAnswerApi | null
    /** Posts after the first, oldest first. */
    replies: DiscussionPostApi[]
    /** not_requested: a post between people. sent: the agent has it. no_run: the thread has no live run, so start one. failed: the run did not take it.
     *
     * * `not_requested` - not_requested
     * * `sent` - sent
     * * `no_run` - no_run
     * * `failed` - failed */
    delivery: DeliveryEnumApi
}

/**
 * A post on an existing thread.
 */
export interface DiscussionReplyApi {
    /** What to add to the thread. */
    content: string
    /**
     * A task the client just started for this thread. The thread keeps it; the post is not forwarded.
     * @maxLength 64
     * @nullable
     */
    task_id?: string | null
    /** True when the post tags the agent. With a live run the text is forwarded into it. */
    send_to_agent?: boolean
}

/**
 * Mark a thread handled, or bring it back.
 */
export interface DiscussionResolveApi {
    /** True marks the thread handled, false reopens it. */
    resolved: boolean
}

/**
 * * `check` - check
 * * `stop` - stop
 * * `resume` - resume
 * * `close` - close
 * * `arm` - arm
 */
export type DocWatchActionEnumApi = (typeof DocWatchActionEnumApi)[keyof typeof DocWatchActionEnumApi]

export const DocWatchActionEnumApi = {
    Check: 'check',
    Stop: 'stop',
    Resume: 'resume',
    Close: 'close',
    Arm: 'arm',
} as const

/**
 * * `confirmed` - confirmed
 * * `refuted` - refuted
 */
export type WatchActionVerdictEnumApi = (typeof WatchActionVerdictEnumApi)[keyof typeof WatchActionVerdictEnumApi]

export const WatchActionVerdictEnumApi = {
    Confirmed: 'confirmed',
    Refuted: 'refuted',
} as const

/**
 * What a person does to a watch.
 */
export interface WatchActionApi {
    /** check runs the evidence now. stop and resume toggle the watch. close sets a final verdict. arm starts the scout when it is missing.
     *
     * * `check` - check
     * * `stop` - stop
     * * `resume` - resume
     * * `close` - close
     * * `arm` - arm */
    action: DocWatchActionEnumApi
    /** With close: confirmed or refuted.
     *
     * * `confirmed` - confirmed
     * * `refuted` - refuted */
    verdict?: WatchActionVerdictEnumApi | null
    /**
     * With close: why.
     * @maxLength 600
     */
    reason?: string
}

/**
 * * `ok` - ok
 * * `none` - none
 */
export type DataPointSubmitStatusEnumApi =
    (typeof DataPointSubmitStatusEnumApi)[keyof typeof DataPointSubmitStatusEnumApi]

export const DataPointSubmitStatusEnumApi = {
    Ok: 'ok',
    None: 'none',
} as const

/**
 * An agent handing in the query behind a data point a page asked for.
 */
export interface DataPointSubmitApi {
    /**
     * The request id named in the task.
     * @maxLength 64
     */
    request_id: string
    /** ok: the query answers the question. none: this project's data cannot answer it.
     *
     * * `ok` - ok
     * * `none` - none */
    status?: DataPointSubmitStatusEnumApi
    /** A HogQL SELECT that returns exactly one row and one column. Required unless status is none. */
    query?: string
    /**
     * What the data point measures, in a few words. The reader sees this on it.
     * @maxLength 120
     */
    label?: string
    /**
     * One short line for the reader: a caveat, or with status none, why there is no answer.
     * @maxLength 400
     */
    note?: string
}

/**
 * Whether the page took the query.
 */
export interface DataPointSubmitResultApi {
    /** True when the page took the query, or took the none status. */
    ok: boolean
    /** How the page shows it: number (one cell), series (a sparkline), or table (a chart block).
     *
     * * `number` - number
     * * `series` - series
     * * `table` - table */
    shape: DocDataShapeEnumApi | null
    /**
     * The cell the page shows: the number, or the last value of a series.
     * @nullable
     */
    value: string | null
    /** How many rows the query returned when it ran once. */
    rows: number
    /** How many columns the query returned when it ran once. */
    columns: number
    /**
     * Why the query was not taken. Fix the query and submit again.
     * @nullable
     */
    error: string | null
}

/**
 * A hypothesis under watch, as the space's home lists it.
 */
export interface WatchSummaryApi {
    /** The watch's thread. */
    thread_id: string
    /** The page the section is on. */
    doc_id: string
    /** Title of that page. */
    doc_title: string
    /** Key of the watched section's thread. */
    anchor_key: string
    /** The words under watch. */
    anchor_text: string
    /** active: checks and the scout run. paused: the page is done. stopped: final.
     *
     * * `active` - active
     * * `paused` - paused
     * * `stopped` - stopped */
    status: DocWatchStatusEnumApi
    /** pending: no brief yet. holding: the evidence stands. moved: a number left its baseline. confirmed or refuted: decided, and the watch ended. stale: the checks could not run.
     *
     * * `pending` - pending
     * * `holding` - holding
     * * `moved` - moved
     * * `confirmed` - confirmed
     * * `refuted` - refuted
     * * `stale` - stale */
    verdict: DocWatchVerdictEnumApi
    /** The agent's newest report, or empty. */
    last_report: string
    /**
     * When that report landed.
     * @nullable
     */
    last_report_at: string | null
    /** When the watch started. */
    created_at: string
}

/**
 * Everything the space home view renders in one call.
 */
export interface SpaceHomeApi {
    /** Docs in this space, in tab order. */
    docs: DocSummaryApi[]
    /** Hypotheses under watch across the space's pages, the ones that moved first. */
    watches: WatchSummaryApi[]
}

/**
 * The new left-to-right order of a space's tabs.
 */
export interface DocReorderApi {
    /** The space (channel) whose docs are being reordered. */
    channel: string
    /** Doc ids in their new order. Ids that are not in this space are ignored. */
    doc_ids: string[]
}

/**
 * An agent handing in the brief behind a watch.
 */
export interface WatchBriefSubmitApi {
    /**
     * The request id named in the task.
     * @maxLength 64
     */
    request_id: string
    /**
     * The claim in one sentence, as the page states it.
     * @maxLength 400
     */
    claim: string
    /**
     * What would confirm it.
     * @maxLength 400
     */
    confirms?: string
    /**
     * What would refute it.
     * @maxLength 400
     */
    refutes?: string
    /** Up to four numbers the claim stands on. */
    evidence?: WatchEvidenceInputApi[]
    /**
     * Up to six things the scout follows: events, flags, experiments, error issues, replay filters.
     * @items.maxLength 200
     */
    signals?: string[]
}

export interface WatchEvidenceResultApi {
    /** The evidence label as submitted. */
    label: string
    /** True when the query ran and gave a number or a trend. */
    ok: boolean
    /**
     * The number, or the last value of the trend.
     * @nullable
     */
    value: string | null
    /**
     * Why it was not taken. Fix the query and submit again.
     * @nullable
     */
    error: string | null
}

/**
 * Whether the page took the brief.
 */
export interface WatchBriefSubmitResultApi {
    /** True when every evidence query ran and the brief was kept. */
    ok: boolean
    /** One result per evidence query, in order. */
    evidence: WatchEvidenceResultApi[]
    /**
     * Why the brief was not taken, or null.
     * @nullable
     */
    error: string | null
}

/**
 * * `holding` - holding
 * * `moved` - moved
 * * `confirmed` - confirmed
 * * `refuted` - refuted
 */
export type WatchVerdictSubmitVerdictEnumApi =
    (typeof WatchVerdictSubmitVerdictEnumApi)[keyof typeof WatchVerdictSubmitVerdictEnumApi]

export const WatchVerdictSubmitVerdictEnumApi = {
    Holding: 'holding',
    Moved: 'moved',
    Confirmed: 'confirmed',
    Refuted: 'refuted',
} as const

/**
 * An agent saying where the claim stands.
 */
export interface WatchVerdictSubmitApi {
    /**
     * The request id named in the task.
     * @maxLength 64
     */
    request_id: string
    /** holding, moved, confirmed, or refuted. Confirmed and refuted end the watch.
     *
     * * `holding` - holding
     * * `moved` - moved
     * * `confirmed` - confirmed
     * * `refuted` - refuted */
    verdict: WatchVerdictSubmitVerdictEnumApi
    /**
     * Why, in one line the reader sees.
     * @maxLength 600
     */
    reason: string
}

export interface DocsSearchRequestApi {
    /** Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question. */
    query: string
}

export interface DocsSearchResponseApi {
    /** Markdown-formatted documentation results. Each block has a title, URL and excerpt; an empty result set returns guidance to navigate to https://posthog.com/docs. */
    content: string
}

export type DocsListParams = {
    /**
     * Only return rows in this space (channel).
     */
    channel?: string
}

export type DocsContextRetrieveParams = {
    /**
     * Only return rows in this space (channel).
     */
    channel?: string
}

export type DocsHomeRetrieveParams = {
    /**
     * Only return rows in this space (channel).
     */
    channel?: string
}
