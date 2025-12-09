import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconChevronLeft, IconExternal, IconFlask, IconPlay, IconPlus, IconRewind } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSkeleton,
    LemonTable,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { MOCK_STUDY } from './fixtures'
import { StudyDetailsSceneLogicProps, studyDetailsSceneLogic } from './studyDetailsSceneLogic'
import type { ParticipantStatus, Round, RoundStatus, Sentiment, Session, Study, ThoughtAction } from './types'

export const scene: SceneExport = {
    component: StudyDetailsSceneWrapper,
}

// ============================================
// Components
// ============================================

function RoundStatusTag({ status }: { status: RoundStatus }): JSX.Element {
    const config: Record<
        RoundStatus,
        { type: 'muted' | 'option' | 'completion' | 'success' | 'danger'; label: string }
    > = {
        draft: { type: 'muted', label: 'Draft' },
        generating: { type: 'option', label: 'Generating...' },
        running: { type: 'completion', label: 'Running...' },
        completed: { type: 'success', label: 'Completed' },
        failed: { type: 'danger', label: 'Failed' },
    }
    return <LemonTag type={config[status].type}>{config[status].label}</LemonTag>
}

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

function formatTimestamp(ms: number): string {
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

function ThoughtActionIcon({ type }: { type: ThoughtAction['type'] }): JSX.Element {
    const icons = {
        thought: '💭',
        action: '👆',
        observation: '👀',
        frustration: '😤',
        success: '✅',
    }
    return <span className="text-base">{icons[type]}</span>
}

function StreamOfConsciousness({ log }: { log: ThoughtAction[] }): JSX.Element {
    return (
        <div className="space-y-2">
            {log.map((entry, i) => (
                <div
                    key={i}
                    className={`flex gap-3 p-2 rounded text-sm ${
                        entry.type === 'frustration'
                            ? 'bg-danger-highlight'
                            : entry.type === 'success'
                              ? 'bg-success-highlight'
                              : 'bg-bg-light'
                    }`}
                >
                    <div className="flex-shrink-0 w-12 text-muted text-xs font-mono pt-0.5">
                        {formatTimestamp(entry.timestamp_ms)}
                    </div>
                    <div className="flex-shrink-0">
                        <ThoughtActionIcon type={entry.type} />
                    </div>
                    <div className="flex-1">
                        <span
                            className={
                                entry.type === 'thought'
                                    ? 'italic text-muted'
                                    : entry.type === 'frustration'
                                      ? 'text-danger'
                                      : entry.type === 'success'
                                        ? 'text-success'
                                        : ''
                            }
                        >
                            {entry.content}
                        </span>
                        {entry.element && (
                            <code className="ml-2 text-xs bg-surface-primary px-1 py-0.5 rounded text-muted">
                                {entry.element}
                            </code>
                        )}
                    </div>
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

function NewRoundModal({
    isOpen,
    onClose,
    nextRoundNumber,
}: {
    isOpen: boolean
    onClose: () => void
    nextRoundNumber: number
}): JSX.Element {
    const [count, setCount] = useState(5)
    const [notes, setNotes] = useState('')

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title={`Start Round ${nextRoundNumber}`} width={500}>
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Number of sessions</label>
                    <p className="text-xs text-muted mt-0.5 mb-1">How many synthetic users should run sessions?</p>
                    <LemonInput
                        type="number"
                        value={count}
                        onChange={(val) => setCount(Number(val))}
                        min={1}
                        max={20}
                        className="w-24"
                    />
                </div>

                <div>
                    <label className="text-sm font-medium">Notes (optional)</label>
                    <p className="text-xs text-muted mt-0.5 mb-1">
                        What changed since the last round? Any tweaks to test?
                    </p>
                    <LemonTextArea
                        value={notes}
                        onChange={setNotes}
                        placeholder="e.g., Added pricing link to signup page, shortened onboarding questions"
                        rows={3}
                    />
                </div>

                <div className="flex justify-end gap-2 pt-2">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" icon={<IconPlay />} onClick={onClose}>
                        Start round
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}

// ============================================
// Tab Components
// ============================================

function OverviewTab({ study }: { study: Study }): JSX.Element {
    const latestRound = study.rounds[study.rounds.length - 1]
    const allSessions = study.rounds.flatMap((r) => r.sessions)
    const completedRounds = study.rounds.filter((r) => r.status === 'completed')

    return (
        <div className="space-y-6">
            {/* Study details */}
            <div className="grid grid-cols-2 gap-6">
                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Target Audience</label>
                    <p className="mt-1">{study.audience_description}</p>
                </div>
                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Research Goal</label>
                    <p className="mt-1">{study.research_goal}</p>
                </div>
                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Target URL</label>
                    <p className="mt-1">
                        <Link
                            to={study.target_url}
                            target="_blank"
                            className="text-link hover:underline flex items-center gap-1"
                        >
                            {study.target_url}
                            <IconExternal className="w-3 h-3" />
                        </Link>
                    </p>
                </div>
                <div>
                    <label className="text-xs text-muted uppercase tracking-wide">Total Sessions</label>
                    <p className="mt-1">
                        {allSessions.length} across {study.rounds.length} round
                        {study.rounds.length !== 1 ? 's' : ''}
                    </p>
                </div>
            </div>

            {/* Latest round summary */}
            {latestRound?.summary && (
                <div className="bg-bg-light border rounded p-4">
                    <h3 className="font-semibold mb-2">Latest Round Summary (Round {latestRound.round_number})</h3>
                    {latestRound.notes && (
                        <p className="text-sm text-muted mb-3 italic">Changes tested: {latestRound.notes}</p>
                    )}
                    <div className="prose prose-sm max-w-none whitespace-pre-wrap">{latestRound.summary}</div>
                </div>
            )}

            {/* Sentiment across all rounds */}
            {completedRounds.length > 0 && (
                <div>
                    <h3 className="font-semibold mb-3">Overall Sentiment ({allSessions.length} sessions)</h3>
                    <div className="flex gap-4">
                        <div className="bg-success-highlight border border-success rounded p-3 flex-1 text-center">
                            <div className="text-2xl font-bold text-success">
                                {allSessions.filter((s) => s.sentiment === 'positive').length}
                            </div>
                            <div className="text-sm text-muted">Positive</div>
                        </div>
                        <div className="bg-bg-light border rounded p-3 flex-1 text-center">
                            <div className="text-2xl font-bold">
                                {allSessions.filter((s) => s.sentiment === 'neutral').length}
                            </div>
                            <div className="text-sm text-muted">Neutral</div>
                        </div>
                        <div className="bg-danger-highlight border border-danger rounded p-3 flex-1 text-center">
                            <div className="text-2xl font-bold text-danger">
                                {allSessions.filter((s) => s.sentiment === 'negative').length}
                            </div>
                            <div className="text-sm text-muted">Negative</div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

function RoundsTab({ study, onNewRound }: { study: Study; onNewRound: () => void }): JSX.Element {
    const [selectedRound, setSelectedRound] = useState<Round | null>(null)
    const [selectedSession, setSelectedSession] = useState<Session | null>(null)

    // Session detail view
    if (selectedSession && selectedRound) {
        return (
            <div className="space-y-4">
                <LemonButton
                    type="tertiary"
                    icon={<IconChevronLeft />}
                    onClick={() => setSelectedSession(null)}
                    size="small"
                >
                    Back to Round {selectedRound.round_number}
                </LemonButton>

                <div className="bg-bg-light border rounded p-4">
                    <div className="flex items-start gap-4 mb-4">
                        <SessionAvatar name={selectedSession.name} size="lg" />
                        <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                                <h3 className="font-semibold text-lg">{selectedSession.name}</h3>
                                <SentimentTag sentiment={selectedSession.sentiment} />
                            </div>
                            <div className="text-muted">{selectedSession.archetype}</div>
                        </div>
                        {selectedSession.session_replay_url && (
                            <LemonButton
                                type="secondary"
                                icon={<IconRewind />}
                                size="small"
                                to={selectedSession.session_replay_url}
                                targetBlank
                            >
                                View session replay
                            </LemonButton>
                        )}
                    </div>

                    <div className="space-y-4">
                        <div>
                            <label className="text-xs text-muted uppercase tracking-wide">Background</label>
                            <p className="mt-1 text-sm">{selectedSession.background}</p>
                        </div>

                        <div>
                            <label className="text-xs text-muted uppercase tracking-wide">Traits</label>
                            <div className="mt-1 flex flex-wrap gap-1">
                                {selectedSession.traits.map((trait) => (
                                    <LemonTag key={trait} type="highlight">
                                        {trait}
                                    </LemonTag>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="text-xs text-muted uppercase tracking-wide">Plan</label>
                            <pre className="mt-1 text-sm bg-surface-primary p-3 rounded whitespace-pre-wrap">
                                {selectedSession.plan}
                            </pre>
                        </div>

                        {selectedSession.experience_writeup && (
                            <div>
                                <label className="text-xs text-muted uppercase tracking-wide">Experience Writeup</label>
                                <div className="mt-1 bg-surface-primary border rounded p-3">
                                    {selectedSession.experience_writeup}
                                </div>
                            </div>
                        )}

                        {selectedSession.key_insights.length > 0 && (
                            <div>
                                <label className="text-xs text-muted uppercase tracking-wide">Key Insights</label>
                                <ul className="mt-1 space-y-1">
                                    {selectedSession.key_insights.map((insight, i) => (
                                        <li key={i} className="flex items-start gap-2 text-sm">
                                            <span className="text-success">•</span>
                                            {insight}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {selectedSession.thought_action_log.length > 0 && (
                            <div>
                                <label className="text-xs text-muted uppercase tracking-wide">
                                    Stream of Consciousness
                                </label>
                                <p className="text-xs text-muted mt-0.5 mb-2">
                                    What the user was thinking and doing throughout the session
                                </p>
                                <StreamOfConsciousness log={selectedSession.thought_action_log} />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        )
    }

    // Round detail view
    if (selectedRound) {
        const completedCount = selectedRound.sessions.filter((s) => s.status === 'completed').length

        return (
            <div className="space-y-4">
                <LemonButton
                    type="tertiary"
                    icon={<IconChevronLeft />}
                    onClick={() => setSelectedRound(null)}
                    size="small"
                >
                    Back to all rounds
                </LemonButton>

                <div className="bg-bg-light border rounded p-4 mb-4">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="font-semibold text-lg">Round {selectedRound.round_number}</h3>
                        <RoundStatusTag status={selectedRound.status} />
                    </div>
                    {selectedRound.notes && (
                        <p className="text-sm text-muted italic mb-2">Changes: {selectedRound.notes}</p>
                    )}
                    <p className="text-sm text-muted">
                        {completedCount}/{selectedRound.session_count} sessions completed
                    </p>
                    {selectedRound.summary && (
                        <div className="mt-3 pt-3 border-t">
                            <div className="prose prose-sm max-w-none whitespace-pre-wrap">{selectedRound.summary}</div>
                        </div>
                    )}
                </div>

                <h4 className="font-medium">Sessions</h4>
                <LemonTable
                    dataSource={selectedRound.sessions}
                    onRow={(session) => ({
                        onClick: () => setSelectedSession(session),
                        className: 'cursor-pointer',
                    })}
                    columns={[
                        {
                            title: 'Session',
                            key: 'name',
                            render: (_, session) => (
                                <div className="flex items-center gap-3">
                                    <SessionAvatar name={session.name} />
                                    <LemonTableLink
                                        title={session.name}
                                        description={session.archetype}
                                        onClick={() => setSelectedSession(session)}
                                    />
                                </div>
                            ),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, session) => <SessionStatusTag status={session.status} />,
                        },
                        {
                            title: 'Sentiment',
                            key: 'sentiment',
                            render: (_, session) => <SentimentTag sentiment={session.sentiment} />,
                        },
                        {
                            title: 'Key insight',
                            key: 'insight',
                            render: (_, session) =>
                                session.key_insights[0] ? (
                                    <span className="text-sm text-muted truncate max-w-xs block">
                                        {session.key_insights[0]}
                                    </span>
                                ) : session.status === 'navigating' ? (
                                    <LemonSkeleton className="w-48 h-4" />
                                ) : (
                                    <span className="text-muted">—</span>
                                ),
                        },
                        {
                            title: '',
                            key: 'replay',
                            width: 0,
                            render: (_, session) =>
                                session.session_replay_url ? (
                                    <LemonButton
                                        type="tertiary"
                                        icon={<IconRewind />}
                                        size="small"
                                        to={session.session_replay_url}
                                        targetBlank
                                        onClick={(e) => e.stopPropagation()}
                                        tooltip="View session replay"
                                    />
                                ) : null,
                        },
                    ]}
                    rowKey="id"
                />
            </div>
        )
    }

    // Rounds list view
    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <p className="text-muted m-0">
                    {study.rounds.length} round{study.rounds.length !== 1 ? 's' : ''}
                </p>
                <LemonButton type="primary" icon={<IconPlus />} size="small" onClick={onNewRound}>
                    New round
                </LemonButton>
            </div>

            <LemonTable
                dataSource={[...study.rounds].reverse()} // newest first
                onRow={(round) => ({
                    onClick: () => setSelectedRound(round),
                    className: 'cursor-pointer',
                })}
                columns={[
                    {
                        title: 'Round',
                        key: 'round_number',
                        render: (_, round) => (
                            <LemonTableLink
                                title={`Round ${round.round_number}`}
                                description={round.notes || 'Initial round'}
                                onClick={() => setSelectedRound(round)}
                            />
                        ),
                    },
                    {
                        title: 'Sessions',
                        key: 'sessions',
                        render: (_, round) => {
                            const completed = round.sessions.filter((s) => s.status === 'completed').length
                            return (
                                <span>
                                    {completed}/{round.session_count}
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, round) => <RoundStatusTag status={round.status} />,
                    },
                    {
                        title: 'Sentiment',
                        key: 'sentiment',
                        render: (_, round) => {
                            if (round.status !== 'completed') {
                                return <span className="text-muted">—</span>
                            }
                            const positive = round.sessions.filter((s) => s.sentiment === 'positive').length
                            const negative = round.sessions.filter((s) => s.sentiment === 'negative').length
                            return (
                                <span className="text-sm">
                                    <span className="text-success">{positive}+</span> /{' '}
                                    <span className="text-danger">{negative}-</span>
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, round) => (
                            <span className="text-sm text-muted">
                                {new Date(round.created_at).toLocaleDateString()}
                            </span>
                        ),
                    },
                ]}
                rowKey="id"
            />
        </div>
    )
}

function InsightsTab({ study }: { study: Study }): JSX.Element {
    const allInsights = study.rounds.flatMap((r) =>
        r.sessions.flatMap((s) =>
            s.key_insights.map((insight) => ({
                insight,
                session: s.name,
                sentiment: s.sentiment,
                round: r.round_number,
            }))
        )
    )

    const completedRounds = study.rounds.filter((r) => r.status === 'completed')

    return (
        <div className="space-y-6">
            {completedRounds.length === 0 ? (
                <LemonBanner type="info">Insights will appear here once a round is completed.</LemonBanner>
            ) : (
                <>
                    <div>
                        <h3 className="font-semibold mb-3">All Insights ({allInsights.length})</h3>
                        <div className="space-y-2">
                            {allInsights.map((item, i) => (
                                <div key={i} className="bg-bg-light border rounded p-3 flex items-start gap-3">
                                    <SentimentTag sentiment={item.sentiment} />
                                    <div className="flex-1">
                                        <p className="text-sm">{item.insight}</p>
                                        <p className="text-xs text-muted mt-1">
                                            — {item.session} (Round {item.round})
                                        </p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div>
                        <h3 className="font-semibold mb-3">Add your notes</h3>
                        <LemonTextArea
                            placeholder="Add observations, action items, or follow-up questions..."
                            rows={4}
                        />
                        <div className="mt-2">
                            <LemonButton type="secondary" size="small">
                                Save notes
                            </LemonButton>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

// ============================================
// Main Scene
// ============================================

function StudyDetailsSceneWrapper({ id }: StudyDetailsSceneLogicProps): JSX.Element {
    return (
        <BindLogic logic={studyDetailsSceneLogic} props={{ id }}>
            <StudyDetailsScene />
        </BindLogic>
    )
}

function StudyDetailsScene(): JSX.Element {
    const { study, studyLoading } = useValues(studyDetailsSceneLogic)
    const [activeTab, setActiveTab] = useState<'overview' | 'rounds' | 'insights'>('overview')
    const [showNewRound, setShowNewRound] = useState(false)

    if (studyLoading) {
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

    if (!study) {
        return <NotFound object="study" />
    }

    // For now, use mock data for rounds since we haven't implemented that yet
    const studyWithRounds = { ...study, rounds: MOCK_STUDY.rounds }
    const latestRound = studyWithRounds.rounds[studyWithRounds.rounds.length - 1]
    const totalSessions = studyWithRounds.rounds.reduce((sum, r) => sum + r.sessions.length, 0)

    return (
        <SceneContent>
            {/* Back button */}
            <div className="mb-4">
                <LemonButton
                    type="tertiary"
                    icon={<IconChevronLeft />}
                    onClick={() => router.actions.push(urls.syntheticUsers())}
                >
                    All studies
                </LemonButton>
            </div>

            {/* Header */}
            <div className="flex items-start justify-between mb-6">
                <div className="flex items-start gap-4">
                    <div className="bg-bg-light rounded p-3">
                        <IconFlask className="w-8 h-8 text-muted" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold">{study.name}</h1>
                        <p className="text-muted mt-1">{study.research_goal}</p>
                        <p className="text-sm text-muted mt-2">
                            {studyWithRounds.rounds.length} round{studyWithRounds.rounds.length !== 1 ? 's' : ''} ·{' '}
                            {totalSessions} sessions
                        </p>
                    </div>
                </div>
                <div className="flex gap-2">
                    <LemonButton type="primary" icon={<IconPlus />} onClick={() => setShowNewRound(true)}>
                        New round
                    </LemonButton>
                </div>
            </div>

            {/* Tabs */}
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as 'overview' | 'rounds' | 'insights')}
                tabs={[
                    {
                        key: 'overview',
                        label: 'Overview',
                        content: <OverviewTab study={studyWithRounds} />,
                    },
                    {
                        key: 'rounds',
                        label: `Rounds (${studyWithRounds.rounds.length})`,
                        content: <RoundsTab study={studyWithRounds} onNewRound={() => setShowNewRound(true)} />,
                    },
                    {
                        key: 'insights',
                        label: 'Insights',
                        content: <InsightsTab study={studyWithRounds} />,
                    },
                ]}
            />

            <NewRoundModal
                isOpen={showNewRound}
                onClose={() => setShowNewRound(false)}
                nextRoundNumber={(latestRound?.round_number ?? 0) + 1}
            />
        </SceneContent>
    )
}
