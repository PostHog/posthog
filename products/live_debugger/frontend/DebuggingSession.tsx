import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { LiveDebuggerSessionEntryListItemApi } from 'products/live_debugger/frontend/generated/api.schemas'

import { debuggingSessionLogic } from './debuggingSessionLogic'

export const scene: SceneExport = {
    component: DebuggingSession,
    logic: debuggingSessionLogic,
    productKey: ProductKey.LIVE_DEBUGGER,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function NoteEntry({ entry }: { entry: LiveDebuggerSessionEntryListItemApi }): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const markdown = String(payload.markdown ?? '')
    return (
        <div className="border rounded p-3 bg-bg-light">
            <div className="text-xs text-muted mb-1">Note · {dayjs(entry.created_at).format('HH:mm:ss')}</div>
            <pre className="whitespace-pre-wrap text-sm font-sans">{markdown}</pre>
        </div>
    )
}

function ConclusionEntry({ entry }: { entry: LiveDebuggerSessionEntryListItemApi }): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const markdown = String(payload.markdown ?? '')
    return (
        <div className="border-2 border-success rounded p-3 bg-success-highlight">
            <div className="text-xs text-success font-semibold mb-1">
                Conclusion · {dayjs(entry.created_at).format('HH:mm:ss')}
            </div>
            <pre className="whitespace-pre-wrap text-sm font-sans">{markdown}</pre>
        </div>
    )
}

function ProgramInstallEntry({ entry }: { entry: LiveDebuggerSessionEntryListItemApi }): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const programId = String(payload.program_id ?? '')
    return (
        <div className="border rounded p-3 bg-bg-3000">
            <div className="text-xs text-muted mb-1">
                Program installed · {dayjs(entry.created_at).format('HH:mm:ss')}
            </div>
            <div className="font-mono text-xs">Program {programId}</div>
        </div>
    )
}

function ProgramUninstallEntry({ entry }: { entry: LiveDebuggerSessionEntryListItemApi }): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const programId = String(payload.program_id ?? '')
    return (
        <div className="text-xs text-muted px-3 py-1">
            Uninstalled program {programId} · {dayjs(entry.created_at).format('HH:mm:ss')}
        </div>
    )
}

function EventHighlightEntry({ entry }: { entry: LiveDebuggerSessionEntryListItemApi }): JSX.Element {
    const payload = (entry.payload ?? {}) as Record<string, unknown>
    const uuids = Array.isArray(payload.event_uuids) ? (payload.event_uuids as string[]) : []
    const caption = String(payload.caption ?? '')
    return (
        <div className="border rounded p-3 bg-warning-highlight">
            <div className="text-xs text-muted mb-1">
                Event highlight · {dayjs(entry.created_at).format('HH:mm:ss')}
            </div>
            <div className="text-sm mb-1">{caption}</div>
            <ul className="text-xs font-mono">
                {uuids.map((u) => (
                    <li key={u}>{u}</li>
                ))}
            </ul>
        </div>
    )
}

function Entry({ entry }: { entry: LiveDebuggerSessionEntryListItemApi }): JSX.Element {
    switch (entry.kind) {
        case 'note':
            return <NoteEntry entry={entry} />
        case 'conclusion':
            return <ConclusionEntry entry={entry} />
        case 'program_install':
            return <ProgramInstallEntry entry={entry} />
        case 'program_uninstall':
            return <ProgramUninstallEntry entry={entry} />
        case 'event_highlight':
            return <EventHighlightEntry entry={entry} />
        default:
            return <div className="text-xs text-muted">Unknown entry kind: {String(entry.kind)}</div>
    }
}

export function DebuggingSession(): JSX.Element {
    const isEnabled = useFeatureFlag('LIVE_DEBUGGER')
    const { session, sessionLoading } = useValues(debuggingSessionLogic)
    const { closeSession } = useActions(debuggingSessionLogic)

    if (!isEnabled) {
        return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
    }
    if (sessionLoading || !session) {
        return <div className="text-muted">Loading…</div>
    }

    return (
        <>
            <SceneTitleSection
                name={session.title}
                description={session.description || undefined}
                resourceType={{ type: 'live_debugger' }}
            />
            <SceneContent>
                <div className="flex items-center justify-between mb-3">
                    <div className="text-xs text-muted">
                        Status: <span className="font-semibold">{session.status}</span> · started{' '}
                        {dayjs(session.created_at).fromNow()}
                        {session.closed_at ? ` · closed ${dayjs(session.closed_at).fromNow()}` : ''}
                    </div>
                    {session.status === 'open' && (
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                const conclusion = window.prompt('Conclusion (optional)') || null
                                closeSession(conclusion)
                            }}
                        >
                            Close session
                        </LemonButton>
                    )}
                </div>
                <div className="deprecated-space-y-2">
                    {(session.entries ?? []).map((e: LiveDebuggerSessionEntryListItemApi) => (
                        <Entry key={e.id} entry={e} />
                    ))}
                    {(session.entries ?? []).length === 0 && <div className="text-muted text-sm">No entries yet.</div>}
                </div>
            </SceneContent>
        </>
    )
}

export default DebuggingSession
