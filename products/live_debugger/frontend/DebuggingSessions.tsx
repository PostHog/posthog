import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { debuggingSessionsLogic } from './debuggingSessionsLogic'

export const scene: SceneExport = {
    component: DebuggingSessions,
    logic: debuggingSessionsLogic,
    productKey: ProductKey.LIVE_DEBUGGER,
}

export function DebuggingSessions(): JSX.Element {
    const isEnabled = useFeatureFlag('LIVE_DEBUGGER')
    const { sessions, sessionsLoading } = useValues(debuggingSessionsLogic)
    const { createSession } = useActions(debuggingSessionsLogic)

    if (!isEnabled) {
        return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
    }

    return (
        <>
            <SceneTitleSection
                name="Debugging sessions"
                description="Investigations the agent has run with hogtrace"
                resourceType={{ type: 'live_debugger' }}
            />

            <SceneContent>
                <div className="flex justify-end mb-2">
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            const title = window.prompt('Session title')
                            if (!title) {
                                return
                            }
                            const description = window.prompt('What are you investigating?') ?? ''
                            createSession({ title, description })
                        }}
                    >
                        New session
                    </LemonButton>
                </div>

                {sessionsLoading ? (
                    <div className="text-muted">Loading…</div>
                ) : sessions.length === 0 ? (
                    <div className="text-muted">No sessions yet.</div>
                ) : (
                    <ul className="divide-y border rounded">
                        {sessions.map((s) => (
                            <li key={s.id} className="p-3 hover:bg-bg-light">
                                <Link to={urls.debuggingSession(s.id)} className="block">
                                    <div className="flex items-center justify-between">
                                        <span className="font-semibold">{s.title}</span>
                                        <span
                                            className={
                                                s.status === 'open' ? 'text-xs text-success' : 'text-xs text-muted'
                                            }
                                        >
                                            {s.status}
                                        </span>
                                    </div>
                                    <div className="text-xs text-muted mt-0.5">
                                        {dayjs(s.created_at).fromNow()}
                                        {s.closed_at ? ` · closed ${dayjs(s.closed_at).fromNow()}` : ''}
                                    </div>
                                    {s.description && <div className="text-sm mt-1">{s.description}</div>}
                                </Link>
                            </li>
                        ))}
                    </ul>
                )}
            </SceneContent>
        </>
    )
}

export default DebuggingSessions
