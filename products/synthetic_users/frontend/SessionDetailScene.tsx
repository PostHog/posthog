import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronLeft, IconPlay, IconRefresh, IconRewind } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { MarkdownMessage } from 'scenes/max/MarkdownMessage'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { sessionDetailSceneLogic } from './sessionDetailSceneLogic'
import type { ParticipantStatus, Sentiment } from './types'

export const scene: SceneExport = {
    component: SessionDetailSceneWrapper,
}

// ============================================
// Components
// ============================================

function SessionStatusTag({ status }: { status: ParticipantStatus }): JSX.Element {
    const config: Record<
        ParticipantStatus,
        { type: 'muted' | 'option' | 'completion' | 'success' | 'danger'; label: string }
    > = {
        pending: { type: 'muted', label: 'Pending' },
        generating: { type: 'option', label: 'Generating...' },
        navigating: { type: 'completion', label: 'Navigating...' },
        completed: { type: 'success', label: 'Completed' },
        failed: { type: 'danger', label: 'Failed' },
    }
    return <LemonTag type={config[status].type}>{config[status].label}</LemonTag>
}

function SentimentTag({ sentiment }: { sentiment: Sentiment | null }): JSX.Element | null {
    if (!sentiment) {
        return null
    }
    const config = {
        positive: { type: 'success' as const, label: '😊 Positive' },
        neutral: { type: 'muted' as const, label: '😐 Neutral' },
        negative: { type: 'danger' as const, label: '😞 Negative' },
    }
    return <LemonTag type={config[sentiment].type}>{config[sentiment].label}</LemonTag>
}

function StreamOfConsciousness({ log }: { log: string[] }): JSX.Element {
    return (
        <div className="space-y-2">
            {log.map((thought, i) => (
                <div key={i} className="flex gap-3 p-2 rounded text-sm bg-bg-light">
                    <div className="flex-shrink-0">
                        <span className="text-base">💭</span>
                    </div>
                    <div className="flex-1 italic text-muted">{thought}</div>
                </div>
            ))}
        </div>
    )
}

const DATA_COLORS = [
    'bg-data-color-1',
    'bg-data-color-2',
    'bg-data-color-3',
    'bg-data-color-4',
    'bg-data-color-5',
    'bg-data-color-6',
    'bg-data-color-7',
    'bg-data-color-8',
    'bg-data-color-9',
    'bg-data-color-10',
]

function stringToDataColor(str: string): string {
    let hash = 0
    for (let i = 0; i < str.length; i++) {
        hash = str.charCodeAt(i) + ((hash << 5) - hash)
    }
    return DATA_COLORS[Math.abs(hash) % DATA_COLORS.length]
}

function getInitials(name: string): string {
    return name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
}

function SessionAvatar({ name, size = 'sm' }: { name: string; size?: 'sm' | 'lg' }): JSX.Element {
    const sizeClasses = size === 'lg' ? 'w-12 h-12 text-lg' : 'w-8 h-8 text-xs'
    return (
        <div
            className={`${sizeClasses} ${stringToDataColor(name)} rounded-full flex items-center justify-center text-white font-semibold`}
        >
            {getInitials(name)}
        </div>
    )
}

// ============================================
// Main Scene
// ============================================

function SessionDetailSceneWrapper({ studyId, sessionId }: { studyId?: string; sessionId?: string }): JSX.Element {
    if (!studyId || !sessionId) {
        return <NotFound object="session" />
    }
    return (
        <BindLogic logic={sessionDetailSceneLogic} props={{ studyId, sessionId }}>
            <SessionDetailScene />
        </BindLogic>
    )
}

function SessionDetailScene(): JSX.Element {
    const { session, study, studyLoading, regeneratedSessionLoading, startedSessionLoading } =
        useValues(sessionDetailSceneLogic)
    const { regenerateSession, startSession } = useActions(sessionDetailSceneLogic)

    if (studyLoading && !session) {
        return (
            <SceneContent>
                <div className="space-y-4">
                    <LemonSkeleton className="h-8 w-48" />
                    <LemonSkeleton className="h-4 w-96" />
                    <LemonSkeleton className="h-64 w-full" />
                </div>
            </SceneContent>
        )
    }

    if (!session || !study) {
        return <NotFound object="session" />
    }

    const canRegenerate = session.status === 'pending'
    const canStart = session.status === 'pending'

    return (
        <SceneContent>
            {/* Back button */}
            <div className="mb-4">
                <LemonButton
                    type="tertiary"
                    icon={<IconChevronLeft />}
                    onClick={() => router.actions.push(urls.syntheticUsersStudy(study.id))}
                >
                    Back to {study.name}
                </LemonButton>
            </div>

            {/* Header */}
            <div className="bg-bg-light border rounded p-4 mb-6">
                <div className="flex items-start gap-4 mb-4">
                    <SessionAvatar name={session.name} size="lg" />
                    <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                            <h1 className="text-2xl font-bold">{session.name}</h1>
                            <SessionStatusTag status={session.status} />
                            <SentimentTag sentiment={session.sentiment} />
                        </div>
                        <div className="text-muted">{session.archetype}</div>
                    </div>
                    <div className="flex gap-2">
                        {canRegenerate && (
                            <LemonButton
                                type="secondary"
                                icon={<IconRefresh />}
                                loading={regeneratedSessionLoading}
                                onClick={() => regenerateSession(session.id)}
                            >
                                Regenerate persona
                            </LemonButton>
                        )}
                        {canStart && (
                            <LemonButton
                                type="primary"
                                icon={<IconPlay />}
                                loading={startedSessionLoading}
                                onClick={() => startSession(session.id)}
                            >
                                Start session
                            </LemonButton>
                        )}
                        {session.session_replay_url && (
                            <LemonButton
                                type="secondary"
                                icon={<IconRewind />}
                                to={session.session_replay_url}
                                targetBlank
                            >
                                View session replay
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>

            {/* Session details */}
            <div className="space-y-6">
                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Background</label>
                    <p className="mt-1">{session.background}</p>
                </div>

                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Traits</label>
                    <div className="mt-1 flex flex-wrap gap-1">
                        {session.traits.map((trait) => (
                            <LemonTag key={trait} type="highlight">
                                {trait}
                            </LemonTag>
                        ))}
                    </div>
                </div>

                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Plan</label>
                    <pre className="mt-1 text-sm bg-surface-primary p-3 rounded whitespace-pre-wrap">
                        {session.plan}
                    </pre>
                </div>

                {session.experience_writeup && (
                    <div>
                        <label className="text-xs text-muted uppercase tracking-wide">Experience Writeup</label>
                        <div className="mt-1 bg-surface-primary border rounded p-3">
                            <MarkdownMessage id="experience-writeup" content={session.experience_writeup} />
                        </div>
                    </div>
                )}

                {session.key_insights.length > 0 && (
                    <div>
                        <label className="text-xs text-muted uppercase tracking-wide">Key Insights</label>
                        <ul className="mt-1 space-y-1">
                            {session.key_insights.map((insight, i) => (
                                <li key={i} className="flex items-start gap-2 text-sm">
                                    <span className="text-success">•</span>
                                    {insight}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}

                {session.thought_action_log.length > 0 && (
                    <div>
                        <label className="text-xs text-muted uppercase tracking-wide">Stream of Consciousness</label>
                        <p className="text-xs text-muted mt-0.5 mb-2">
                            What the user was thinking and doing throughout the session
                        </p>
                        <StreamOfConsciousness log={session.thought_action_log} />
                    </div>
                )}
            </div>
        </SceneContent>
    )
}
