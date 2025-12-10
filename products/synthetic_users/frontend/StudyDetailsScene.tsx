import { BindLogic, useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import {
    IconChevronLeft,
    IconExternal,
    IconFlask,
    IconGear,
    IconPlay,
    IconPlus,
    IconRefresh,
    IconRewind,
} from '@posthog/icons'
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

import { studyDetailsSceneLogic } from './studyDetailsSceneLogic'
import type { ParticipantStatus, RoundStatus, Sentiment, Session, Study } from './types'

export const scene: SceneExport = {
    component: StudyDetailsSceneWrapper,
}

// ============================================
// Components
// ============================================

function RoundStatusTag({ status }: { status: RoundStatus }): JSX.Element {
    const config: Record<
        RoundStatus,
        { type: 'muted' | 'option' | 'completion' | 'success' | 'danger' | 'highlight'; label: string }
    > = {
        draft: { type: 'muted', label: 'Draft' },
        generating: { type: 'option', label: 'Generating...' },
        ready: { type: 'highlight', label: 'Ready' },
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

function NewRoundModal({ nextRoundNumber }: { nextRoundNumber: number }): JSX.Element {
    const { showNewRoundModal, isRoundFormSubmitting, roundFormHasErrors } = useValues(studyDetailsSceneLogic)
    const { setShowNewRoundModal, resetRoundForm } = useActions(studyDetailsSceneLogic)

    const handleClose = (): void => {
        resetRoundForm()
        setShowNewRoundModal(false)
    }

    return (
        <LemonModal
            isOpen={showNewRoundModal}
            onClose={handleClose}
            title={`Create Round ${nextRoundNumber}`}
            width={500}
        >
            <Form logic={studyDetailsSceneLogic} formKey="roundForm" enableFormOnSubmit>
                <div className="space-y-4">
                    <Field
                        name="session_count"
                        label="Number of sessions"
                        hint="How many synthetic users should run sessions?"
                    >
                        {({ value, onChange }) => (
                            <LemonInput
                                type="number"
                                value={value}
                                onChange={(val) => onChange(Number(val))}
                                min={1}
                                max={20}
                                className="w-24"
                            />
                        )}
                    </Field>

                    <Field
                        name="notes"
                        label="Notes (optional)"
                        hint="What changed since the last round? Any tweaks to test?"
                    >
                        {({ value, onChange }) => (
                            <LemonTextArea
                                value={value}
                                onChange={onChange}
                                placeholder="e.g., Added pricing link to signup page, shortened onboarding questions"
                                rows={3}
                            />
                        )}
                    </Field>

                    <div className="flex justify-end gap-2 pt-2">
                        <LemonButton type="secondary" onClick={handleClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            htmlType="submit"
                            loading={isRoundFormSubmitting}
                            disabledReason={roundFormHasErrors ? 'Please fix the errors' : undefined}
                        >
                            Create draft
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}

// ============================================
// Tab Components
// ============================================

function OverviewTab({ study }: { study: Study }): JSX.Element {
    const rounds = study.rounds || []
    const latestRound = rounds[rounds.length - 1]
    const allSessions = rounds.flatMap((r) => r.sessions || [])
    const completedRounds = rounds.filter((r) => r.status === 'completed')

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
                        {allSessions.length} across {rounds.length} round
                        {rounds.length !== 1 ? 's' : ''}
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
    const {
        selectedRoundId,
        generatedRoundLoading,
        startedRoundLoading,
        regeneratedSessionLoading,
        startedSessionLoading,
    } = useValues(studyDetailsSceneLogic)
    const { setSelectedRoundId, generateSessionsWithPolling, startRound, regenerateSession, startSession } =
        useActions(studyDetailsSceneLogic)

    // Get selected round from study data (keeps it in sync after reloads)
    const selectedRound = selectedRoundId ? (study.rounds || []).find((r) => r.id === selectedRoundId) || null : null

    // Clear selection if round no longer exists
    useEffect(() => {
        if (selectedRoundId && !selectedRound) {
            setSelectedRoundId(null)
        }
    }, [selectedRoundId, selectedRound, setSelectedRoundId])

    const navigateToSession = (sessionId: string): void => {
        router.actions.push(urls.syntheticUsersSession(study.id, sessionId))
    }

    // Round detail view
    if (selectedRound) {
        const sessions = selectedRound.sessions || []
        const completedCount = sessions.filter((s) => s.status === 'completed').length
        const isDraft = selectedRound.status === 'draft'
        const isGenerating = selectedRound.status === 'generating'
        const isReady = selectedRound.status === 'ready'
        const canRegenerate = isDraft || isReady

        return (
            <div className="space-y-4">
                <LemonButton
                    type="tertiary"
                    icon={<IconChevronLeft />}
                    onClick={() => setSelectedRoundId(null)}
                    size="small"
                >
                    Back to all rounds
                </LemonButton>

                <div className="bg-bg-light border rounded p-4 mb-4">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="font-semibold text-lg">Round {selectedRound.round_number}</h3>
                        <div className="flex items-center gap-2">
                            <RoundStatusTag status={selectedRound.status} />
                            {isReady && (
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlay />}
                                    size="small"
                                    loading={startedRoundLoading}
                                    onClick={() => startRound(selectedRound.id)}
                                >
                                    Start round
                                </LemonButton>
                            )}
                        </div>
                    </div>
                    {selectedRound.notes && (
                        <p className="text-sm text-muted italic mb-2">Changes: {selectedRound.notes}</p>
                    )}
                    <p className="text-sm text-muted">
                        {isDraft || isGenerating
                            ? `${selectedRound.session_count} sessions to generate`
                            : `${completedCount}/${selectedRound.session_count} sessions completed`}
                    </p>
                    {selectedRound.summary && (
                        <div className="mt-3 pt-3 border-t">
                            <div className="prose prose-sm max-w-none whitespace-pre-wrap">{selectedRound.summary}</div>
                        </div>
                    )}
                </div>

                {/* Draft state: Generate personas button */}
                {isDraft && sessions.length === 0 && (
                    <div className="border-2 border-dashed rounded-lg p-8 text-center">
                        <div className="text-4xl mb-3">🎭</div>
                        <h4 className="font-semibold mb-2">Generate personas</h4>
                        <p className="text-muted text-sm mb-4 max-w-md mx-auto">
                            Create {selectedRound.session_count} synthetic users who match your target audience. Review
                            and tweak them before starting the round.
                        </p>
                        <LemonButton
                            type="primary"
                            icon={<IconPlay />}
                            loading={generatedRoundLoading}
                            onClick={() => generateSessionsWithPolling(selectedRound.id)}
                        >
                            Generate {selectedRound.session_count} personas
                        </LemonButton>
                    </div>
                )}

                {/* Generating state: Show progress and sessions as they appear */}
                {isGenerating && (
                    <div className="border rounded-lg p-4 bg-bg-light">
                        <div className="flex items-center gap-3 mb-2">
                            <div className="text-2xl animate-pulse">🎭</div>
                            <div>
                                <h4 className="font-semibold">Generating personas...</h4>
                                <p className="text-muted text-sm">
                                    {sessions.length} of {selectedRound.session_count} created
                                </p>
                            </div>
                        </div>
                        <div className="w-full bg-border rounded-full h-2">
                            <div
                                className="bg-primary h-2 rounded-full transition-all duration-300"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ width: `${(sessions.length / selectedRound.session_count) * 100}%` }}
                            />
                        </div>
                    </div>
                )}

                {/* Sessions list (when we have them) */}
                {sessions.length > 0 && (
                    <>
                        <div className="flex items-center justify-between">
                            <h4 className="font-medium">
                                {canRegenerate ? 'Review personas' : isGenerating ? 'Generated so far' : 'Sessions'} (
                                {sessions.length})
                            </h4>
                            {canRegenerate && (
                                <p className="text-sm text-muted">Click regenerate to get a different persona</p>
                            )}
                        </div>
                        <LemonTable
                            dataSource={sessions}
                            onRow={(session) => ({
                                onClick: () => navigateToSession(session.id),
                                className: 'cursor-pointer',
                            })}
                            columns={[
                                {
                                    title: 'Persona',
                                    key: 'name',
                                    render: (_, session) => (
                                        <div className="flex items-center gap-3">
                                            <SessionAvatar name={session.name} />
                                            <LemonTableLink
                                                title={session.name}
                                                description={session.archetype}
                                                onClick={() => navigateToSession(session.id)}
                                            />
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Background',
                                    key: 'background',
                                    render: (_, session) => (
                                        <span className="text-sm text-muted truncate max-w-xs block">
                                            {session.background}
                                        </span>
                                    ),
                                },
                                ...(canRegenerate
                                    ? []
                                    : [
                                          {
                                              title: 'Status',
                                              key: 'status',
                                              render: (_: any, session: Session) => (
                                                  <SessionStatusTag status={session.status} />
                                              ),
                                          },
                                          {
                                              title: 'Sentiment',
                                              key: 'sentiment',
                                              render: (_: any, session: Session) => (
                                                  <SentimentTag sentiment={session.sentiment} />
                                              ),
                                          },
                                          {
                                              title: 'Key insight',
                                              key: 'insight',
                                              render: (_: any, session: Session) =>
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
                                      ]),
                                {
                                    title: '',
                                    key: 'actions',
                                    width: 0,
                                    render: (_, session) =>
                                        canRegenerate ? (
                                            <div className="flex gap-1">
                                                <LemonButton
                                                    type="secondary"
                                                    icon={<IconRefresh />}
                                                    size="small"
                                                    loading={regeneratedSessionLoading}
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        regenerateSession(session.id)
                                                    }}
                                                    tooltip="Regenerate persona"
                                                />
                                                {isReady && session.status === 'pending' && (
                                                    <LemonButton
                                                        type="primary"
                                                        icon={<IconPlay />}
                                                        size="small"
                                                        loading={startedSessionLoading}
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            startSession(session.id)
                                                        }}
                                                        tooltip="Start this session"
                                                    />
                                                )}
                                            </div>
                                        ) : session.session_replay_url ? (
                                            <LemonButton
                                                type="tertiary"
                                                icon={<IconRewind />}
                                                size="small"
                                                to={session.session_replay_url}
                                                targetBlank
                                                onClick={(e) => e.stopPropagation()}
                                                tooltip="View session replay"
                                            />
                                        ) : session.status === 'pending' ? (
                                            <LemonButton
                                                type="primary"
                                                icon={<IconPlay />}
                                                size="small"
                                                loading={startedSessionLoading}
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    startSession(session.id)
                                                }}
                                                tooltip="Start this session"
                                            />
                                        ) : null,
                                },
                            ]}
                            rowKey="id"
                        />
                    </>
                )}
            </div>
        )
    }

    // Rounds list view
    const studyRounds = study.rounds || []
    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center">
                <p className="text-muted m-0">
                    {studyRounds.length} round{studyRounds.length !== 1 ? 's' : ''}
                </p>
                <LemonButton type="primary" icon={<IconPlus />} size="small" onClick={onNewRound}>
                    New round
                </LemonButton>
            </div>

            <LemonTable
                dataSource={[...studyRounds].reverse()} // newest first
                onRow={(round) => ({
                    onClick: () => setSelectedRoundId(round.id),
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
                                onClick={() => setSelectedRoundId(round.id)}
                            />
                        ),
                    },
                    {
                        title: 'Sessions',
                        key: 'sessions',
                        render: (_, round) => {
                            const sessions = round.sessions || []
                            const completed = sessions.filter((s) => s.status === 'completed').length
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
                            const sessions = round.sessions || []
                            if (round.status !== 'completed' || sessions.length === 0) {
                                return <span className="text-muted">—</span>
                            }
                            const positive = sessions.filter((s) => s.sentiment === 'positive').length
                            const negative = sessions.filter((s) => s.sentiment === 'negative').length
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
                    {
                        title: '',
                        key: 'actions',
                        width: 0,
                        render: (_, round) => {
                            if (round.status === 'draft') {
                                return (
                                    <LemonButton
                                        type="secondary"
                                        icon={<IconGear />}
                                        size="small"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            setSelectedRoundId(round.id)
                                        }}
                                    >
                                        Configure
                                    </LemonButton>
                                )
                            }
                            if (round.status === 'ready') {
                                return (
                                    <LemonButton
                                        type="primary"
                                        icon={<IconPlay />}
                                        size="small"
                                        loading={startedRoundLoading}
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            startRound(round.id)
                                        }}
                                    >
                                        Start
                                    </LemonButton>
                                )
                            }
                            return null
                        },
                    },
                ]}
                rowKey="id"
            />
        </div>
    )
}

function InsightsTab({ study }: { study: Study }): JSX.Element {
    const rounds = study.rounds || []
    const allInsights = rounds.flatMap((r) =>
        (r.sessions || []).flatMap((s) =>
            s.key_insights.map((insight) => ({
                insight,
                session: s.name,
                sentiment: s.sentiment,
                round: r.round_number,
            }))
        )
    )

    const completedRounds = rounds.filter((r) => r.status === 'completed')

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

function StudyDetailsSceneWrapper({ studyId }: { studyId?: string }): JSX.Element {
    if (!studyId) {
        return <NotFound object="study" />
    }
    return (
        <BindLogic logic={studyDetailsSceneLogic} props={{ id: studyId }}>
            <StudyDetailsScene />
        </BindLogic>
    )
}

function StudyDetailsScene(): JSX.Element {
    const { study, studyLoading } = useValues(studyDetailsSceneLogic)
    const { setShowNewRoundModal } = useActions(studyDetailsSceneLogic)
    const [activeTab, setActiveTab] = useState<'overview' | 'rounds' | 'insights'>('overview')

    // Only show skeleton on initial load (no data yet)
    if (studyLoading && !study) {
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

    const rounds = study.rounds || []
    const latestRound = rounds[rounds.length - 1]
    const totalSessions = rounds.reduce((sum, r) => sum + r.session_count, 0)

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
                            {rounds.length} round{rounds.length !== 1 ? 's' : ''} · {totalSessions} sessions
                        </p>
                    </div>
                </div>
                <div className="flex gap-2">
                    <LemonButton type="primary" icon={<IconPlus />} onClick={() => setShowNewRoundModal(true)}>
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
                        content: <OverviewTab study={study} />,
                    },
                    {
                        key: 'rounds',
                        label: `Rounds (${rounds.length})`,
                        content: <RoundsTab study={study} onNewRound={() => setShowNewRoundModal(true)} />,
                    },
                    {
                        key: 'insights',
                        label: 'Insights',
                        content: <InsightsTab study={study} />,
                    },
                ]}
            />

            <NewRoundModal nextRoundNumber={(latestRound?.round_number ?? 0) + 1} />
        </SceneContent>
    )
}
