import './DebuggingSession.scss'

import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconBug } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'

import type {
    LiveDebuggerProgramApi,
    LiveDebuggerSessionEntryListItemApi,
    ProgramEventApi,
} from 'products/live_debugger/frontend/generated/api.schemas'

import { debuggingSessionLogic } from './debuggingSessionLogic'

export const scene: SceneExport = {
    component: DebuggingSession,
    logic: debuggingSessionLogic,
    productKey: ProductKey.LIVE_DEBUGGER,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

// ─── helpers ────────────────────────────────────────────────────────────────────

function clockTime(iso: string): string {
    return dayjs(iso).format('HH:mm:ss')
}
function clockTimeMs(iso: string): string {
    return dayjs(iso).format('HH:mm:ss.SSS')
}

function formatCaptureValue(value: unknown): { text: string; kind: 'str' | 'num' | 'json' | 'bare' } {
    if (typeof value === 'string') {
        return { text: value, kind: 'str' }
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return { text: String(value), kind: 'num' }
    }
    if (value === null || value === undefined) {
        return { text: String(value), kind: 'bare' }
    }
    return { text: JSON.stringify(value, null, 2), kind: 'json' }
}

function pickSourceContext(event: ProgramEventApi): string | undefined {
    // Forward-compat: libdebugger is adding the Python source at the probe site
    // to the event payload. Field name is in flux; probe a few likely candidates.
    const e = event as unknown as Record<string, unknown>
    for (const key of ['source_context', 'source', 'target_source', 'code_context', 'source_lines']) {
        const value = e[key]
        if (typeof value === 'string' && value.trim()) {
            return value
        }
        if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
            return (value as string[]).join('\n')
        }
    }
    return undefined
}

// ─── hogtrace syntax highlighting ───────────────────────────────────────────────

// Lightweight tokenizer for the hogtrace DSL — turns source text into spans.
// Honors: fn:/capture/sample keywords, :entry/:exit/:return/:line events,
// dotted module paths after `fn:`, request-scoped $req.* / $task.*, punctuation.
function HogtraceSource({ code }: { code: string }): JSX.Element {
    const out: JSX.Element[] = []
    let key = 0
    const lines = code.split('\n')
    lines.forEach((line, lineIdx) => {
        let remaining = line
        while (remaining.length > 0) {
            // fn: keyword
            let m = remaining.match(/^(fn|capture|sample|predicate)\b/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-k">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // :event keyword (entry/exit/return/line)
            m = remaining.match(/^:(entry|exit|return|line)\b/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-ev">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // dotted path: letters then .letters repeated, possibly with wildcards
            m = remaining.match(/^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_*]*)+/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-p">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // $req.x / $task.x / $session.x
            m = remaining.match(/^\$[a-zA-Z_][a-zA-Z0-9_.]*/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-d">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // string literal
            m = remaining.match(/^"[^"\n]*"/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-s">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // number
            m = remaining.match(/^\d+(?:\.\d+)?/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-num">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // identifier
            m = remaining.match(/^[a-zA-Z_][a-zA-Z0-9_]*/)
            if (m) {
                out.push(
                    <span key={key++} className="hg-a">
                        {m[0]}
                    </span>
                )
                remaining = remaining.slice(m[0].length)
                continue
            }
            // punctuation / whitespace / anything else: emit one char as muted
            const ch = remaining[0]
            out.push(
                <span key={key++} className="hg-n">
                    {ch}
                </span>
            )
            remaining = remaining.slice(1)
        }
        if (lineIdx < lines.length - 1) {
            out.push(<span key={key++}>{'\n'}</span>)
        }
    })
    return <pre className="hg-source">{out}</pre>
}

// ─── timeline entries ───────────────────────────────────────────────────────────

function NoteEntry({
    entry,
    isConclusion = false,
}: {
    entry: LiveDebuggerSessionEntryListItemApi
    isConclusion?: boolean
}): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const markdown = String(payload.markdown ?? '')
    return (
        <article className={`tl-entry ${isConclusion ? 'tl-entry--conclusion' : 'tl-entry--note'}`}>
            <div className="tl-entry__head">
                <span className="tl-entry__label">{isConclusion ? 'Conclusion' : 'Note'}</span>
                <span className="tl-entry__when">{clockTime(entry.created_at)}</span>
            </div>
            <div className="tl-card">
                <LemonMarkdown className="tl-prose">{markdown}</LemonMarkdown>
            </div>
        </article>
    )
}

function ProgramInstallEntry({
    entry,
    program,
}: {
    entry: LiveDebuggerSessionEntryListItemApi
    program: LiveDebuggerProgramApi | undefined
}): JSX.Element {
    const [expanded, setExpanded] = useState(true)
    const description = program?.description?.trim() || 'Hogtrace program'
    const status = program?.status ?? 'unknown'
    return (
        <article className="tl-entry tl-entry--program">
            <div className="tl-entry__head">
                <span className="tl-entry__label">Program installed</span>
                <span className="tl-entry__when">{clockTime(entry.created_at)}</span>
                {program?.code && (
                    <button type="button" onClick={() => setExpanded((v) => !v)} className="tl-entry__action">
                        {expanded ? 'Hide source' : 'Show source'}
                    </button>
                )}
            </div>
            <div className="tl-card">
                <h3 className="tl-card__title">{description}</h3>
                {program && (
                    <p className="tl-card__sub">
                        <span className="tl-card__sub-id">{program.id}</span>
                        <span className="tl-card__sub-sep">·</span>
                        <span className={`tl-card__sub-status tl-card__sub-status--${status}`}>{status}</span>
                    </p>
                )}
                {program?.code && expanded && <HogtraceSource code={program.code} />}
            </div>
        </article>
    )
}

function ProgramUninstallEntry({
    entry,
    program,
}: {
    entry: LiveDebuggerSessionEntryListItemApi
    program: LiveDebuggerProgramApi | undefined
}): JSX.Element {
    const desc =
        program?.description?.trim() ||
        `program ${String((entry.payload as Record<string, unknown>)?.program_id ?? '').slice(0, 8)}`
    return (
        <article className="tl-entry tl-entry--system">
            <div className="tl-entry__head">
                <span className="tl-entry__system-text">
                    Uninstalled <em>{desc}</em>
                </span>
                <span className="tl-entry__when tl-entry__when--system">{clockTime(entry.created_at)}</span>
            </div>
        </article>
    )
}

function EventHit({
    event,
    program,
    onShowProbe,
}: {
    event: ProgramEventApi
    program: LiveDebuggerProgramApi | undefined
    onShowProbe: () => void
}): JSX.Element {
    const captures = (event.captures ?? {}) as Record<string, unknown>
    const probeSpec = (event.probe_spec ?? {}) as Record<string, unknown>
    const specifier = typeof probeSpec.specifier === 'string' ? probeSpec.specifier : undefined
    const target = typeof probeSpec.target === 'string' ? probeSpec.target : undefined
    const targetSource = pickSourceContext(event)
    const captureEntries = Object.entries(captures)

    let dotted: string | undefined
    let leaf: string | undefined
    if (specifier) {
        const lastDot = specifier.lastIndexOf('.')
        if (lastDot > 0) {
            dotted = `${specifier.slice(0, lastDot + 1)}`
            leaf = specifier.slice(lastDot + 1)
        } else {
            leaf = specifier
        }
    }

    return (
        <div className="hit">
            <div className="hit-head">
                <span className="hit-head__ts">{clockTimeMs(event.timestamp)}</span>
                <span className="hit-head__fn" title={specifier}>
                    {dotted && <span className="hit-head__fn-dim">{dotted}</span>}
                    <span className="hit-head__fn-leaf">
                        {leaf ?? '(unknown probe)'}
                        {target ? `:${target}` : ''}
                    </span>
                </span>
                {event.thread_name && <span className="hit-head__thread">thread {event.thread_name}</span>}
            </div>

            <div className="hit-body">
                <p className="hit-section">Source at hit site</p>
                {targetSource ? (
                    <pre className="hit-source">{targetSource}</pre>
                ) : (
                    <p className="hit-source-pending">
                        Not in event payload yet (pending libdebugger change to ship target source with probe hits).
                    </p>
                )}

                <p className="hit-section">Captured locals</p>
                {captureEntries.length > 0 ? (
                    <div className="locals">
                        {captureEntries.map(([k, v]) => {
                            const { text, kind } = formatCaptureValue(v)
                            const isMultiline = text.includes('\n')
                            return (
                                <div className="locals__row" key={k}>
                                    <div className="locals__k">{k}</div>
                                    <div className={`locals__v locals__v--${kind}`}>
                                        {isMultiline ? <pre>{text}</pre> : text}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                ) : (
                    <p className="hit-source-pending">No captures — probe body wrote no capture(name=value) calls.</p>
                )}

                {program?.code && (
                    <div className="hit-actions">
                        <button type="button" onClick={onShowProbe} className="hit-actions__link">
                            Show hogtrace probe source →
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}

function EventHighlightEntry({
    entry,
    eventsByUuid,
    programsById,
}: {
    entry: LiveDebuggerSessionEntryListItemApi
    eventsByUuid: Record<string, ProgramEventApi>
    programsById: Record<string, LiveDebuggerProgramApi>
}): JSX.Element {
    const [shownProbeIds, setShownProbeIds] = useState<Set<string>>(new Set())
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const uuids = Array.isArray(payload.event_uuids) ? (payload.event_uuids as string[]) : []
    const caption = String(payload.caption ?? '')
    const resolved = uuids.map((u) => ({ uuid: u, event: eventsByUuid[u] }))
    const presentEvents = resolved.filter((r) => r.event)
    const missingCount = resolved.length - presentEvents.length

    return (
        <article className="tl-entry tl-entry--event">
            <div className="tl-entry__head">
                <span className="tl-entry__label">Event highlight</span>
                <span className="tl-entry__when">{clockTime(entry.created_at)}</span>
            </div>

            <div className="event-card">
                <div className="event-head">
                    <h3 className="event-head__title">{caption || 'Highlighted events'}</h3>
                    <span className="event-head__count">
                        {presentEvents.length} hit{presentEvents.length === 1 ? '' : 's'}
                        {missingCount > 0 ? ` · ${missingCount} pending` : ''}
                    </span>
                </div>

                {presentEvents.length === 0 && missingCount > 0 ? (
                    <p className="event-summary">
                        Events pinned but not yet flushed to ClickHouse — reload in a moment.
                    </p>
                ) : null}

                {presentEvents.map(({ uuid, event }) => {
                    if (!event) {
                        return null
                    }
                    const program = programsById[event.program_id]
                    const probeShown = shownProbeIds.has(event.program_id)
                    return (
                        <div key={uuid}>
                            <EventHit
                                event={event}
                                program={program}
                                onShowProbe={() =>
                                    setShownProbeIds((current) => {
                                        const next = new Set(current)
                                        if (next.has(event.program_id)) {
                                            next.delete(event.program_id)
                                        } else {
                                            next.add(event.program_id)
                                        }
                                        return next
                                    })
                                }
                            />
                            {probeShown && program?.code && (
                                <div className="hit-probe-reveal">
                                    <p className="hit-section">Hogtrace probe source</p>
                                    <HogtraceSource code={program.code} />
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </article>
    )
}

function ClosedEntry({ session }: { session: { closed_at?: string | null } }): JSX.Element | null {
    if (!session.closed_at) {
        return null
    }
    return (
        <article className="tl-entry tl-entry--system">
            <div className="tl-entry__head">
                <span className="tl-entry__system-text">Session closed</span>
                <span className="tl-entry__when tl-entry__when--system">{clockTime(session.closed_at)}</span>
            </div>
        </article>
    )
}

function Entry({
    entry,
    programsById,
    eventsByUuid,
}: {
    entry: LiveDebuggerSessionEntryListItemApi
    programsById: Record<string, LiveDebuggerProgramApi>
    eventsByUuid: Record<string, ProgramEventApi>
}): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const programId = String(payload.program_id ?? '')
    switch (entry.kind) {
        case 'note':
            return <NoteEntry entry={entry} />
        case 'conclusion':
            return <NoteEntry entry={entry} isConclusion />
        case 'program_install':
            return <ProgramInstallEntry entry={entry} program={programsById[programId]} />
        case 'program_uninstall':
            return <ProgramUninstallEntry entry={entry} program={programsById[programId]} />
        case 'event_highlight':
            return <EventHighlightEntry entry={entry} eventsByUuid={eventsByUuid} programsById={programsById} />
        default:
            return <div className="tl-card text-xs text-muted">Unknown entry kind: {String(entry.kind)}</div>
    }
}

// ─── scene ──────────────────────────────────────────────────────────────────────

export function DebuggingSession(): JSX.Element {
    const isEnabled = useFeatureFlag('LIVE_DEBUGGER')
    const { session, sessionLoading, eventsByUuid } = useValues(debuggingSessionLogic)
    const { closeSession } = useActions(debuggingSessionLogic)

    const programsById = useMemo(() => {
        const map: Record<string, LiveDebuggerProgramApi> = {}
        for (const program of session?.programs ?? []) {
            map[program.id] = program
        }
        return map
    }, [session?.programs])

    if (!isEnabled) {
        return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
    }
    if (sessionLoading || !session) {
        return <div className="text-muted p-6">Loading session…</div>
    }

    const entries = session.entries ?? []
    const programCount = (session.programs ?? []).length
    const noteCount = entries.filter((e) => e.kind === 'note' || e.kind === 'conclusion').length
    const hitCount = entries
        .filter((e) => e.kind === 'event_highlight')
        .reduce((sum, e) => {
            const uuids = (e.payload as Record<string, unknown>)?.event_uuids
            return sum + (Array.isArray(uuids) ? uuids.length : 0)
        }, 0)
    const isClosed = session.status === 'closed'
    const shortId = session.id.slice(0, 8)

    return (
        <SceneContent>
            <div className="debugging-session">
                <header className="ds-header">
                    <div className="ds-eyebrow">
                        <span className={`ds-pill ${isClosed ? 'ds-pill--closed' : 'ds-pill--open'}`}>
                            <span className="ds-pill__dot" />
                            {isClosed ? 'Closed' : 'Open'}
                        </span>
                        <span className="ds-pill">
                            <span className="ds-pill__dot" />
                            {programCount} program{programCount === 1 ? '' : 's'} · {noteCount} note
                            {noteCount === 1 ? '' : 's'} · {hitCount} hit{hitCount === 1 ? '' : 's'}
                        </span>
                        <span className="ds-pill ds-pill--mono">
                            <span className="ds-pill__dot" />
                            session ds_{shortId}
                        </span>
                    </div>

                    <h1 className="ds-title">
                        <span className="ds-title__icon" aria-hidden="true">
                            <IconBug />
                        </span>
                        <span>{session.title}</span>
                    </h1>

                    {session.description && <p className="ds-description">{session.description}</p>}

                    <div className="ds-meta">
                        <div>
                            <span className="ds-meta__k">Started</span>
                            <span className="ds-meta__v">
                                {dayjs(session.created_at).fromNow()}
                                <span className="ds-meta__sub"> · {dayjs(session.created_at).format('HH:mm')}</span>
                            </span>
                        </div>
                        {session.closed_at && (
                            <div>
                                <span className="ds-meta__k">Closed</span>
                                <span className="ds-meta__v">
                                    {dayjs(session.closed_at).fromNow()}
                                    <span className="ds-meta__sub"> · {dayjs(session.closed_at).format('HH:mm')}</span>
                                </span>
                            </div>
                        )}
                        <div>
                            <span className="ds-meta__k">Session</span>
                            <span className="ds-meta__v ds-meta__v--mono">{session.id}</span>
                        </div>
                    </div>
                </header>

                <div className="timeline">
                    {entries.map((e: LiveDebuggerSessionEntryListItemApi) => (
                        <Entry key={e.id} entry={e} programsById={programsById} eventsByUuid={eventsByUuid} />
                    ))}
                    {entries.length === 0 && <div className="tl-empty">No entries yet.</div>}
                    {isClosed && <ClosedEntry session={session} />}
                </div>

                {!isClosed && (
                    <div className="ds-composer">
                        <span className="ds-composer__add">+</span>
                        <span className="ds-composer__hint">Close this session when you're done</span>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                const conclusion = window.prompt('Conclusion (optional)') || null
                                closeSession(conclusion)
                            }}
                        >
                            Close session
                        </LemonButton>
                    </div>
                )}
            </div>
        </SceneContent>
    )
}

export default DebuggingSession
