import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconCheck, IconChevronRight, IconClock, IconDownload } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, LemonWidget } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import type { UserInterviewTopicApi } from './generated/api.schemas'
import { InterviewLinkCopyButton } from './InterviewLinkCopyButton'
import { UserInterviewLogicProps, userInterviewLogic } from './userInterviewLogic'

export const scene: SceneExport<UserInterviewLogicProps> = {
    component: UserInterview,
    logic: userInterviewLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function targetingLabel(topic: UserInterviewTopicApi): string {
    const emailCount = topic.interviewee_emails?.length || 0
    const distinctIdCount = topic.interviewee_distinct_ids?.length || 0
    const parts: string[] = []
    if (emailCount > 0) {
        parts.push(`${emailCount} email${emailCount !== 1 ? 's' : ''}`)
    }
    if (distinctIdCount > 0) {
        parts.push(`${distinctIdCount} ID${distinctIdCount !== 1 ? 's' : ''}`)
    }
    return parts.length > 0 ? parts.join(' + ') : 'Not set'
}

export function UserInterview({ id }: UserInterviewLogicProps): JSX.Element {
    const {
        topic,
        topicLoading,
        interviewees,
        intervieweesLoading,
        respondedIdentifiers,
        respondedCount,
        totalTargeted,
        responseRate,
        linksCsvExporting,
    } = useValues(userInterviewLogic)
    const { exportLinksCsv } = useActions(userInterviewLogic)

    if (topicLoading && !topic) {
        return (
            <SceneContent>
                <div className="space-y-4">
                    <LemonSkeleton.Text className="h-8 w-[60%]" />
                    <LemonSkeleton.Text className="h-4 w-[40%]" />
                    <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4">
                        <LemonSkeleton className="h-24" />
                        <LemonSkeleton className="h-24" />
                        <LemonSkeleton className="h-24" />
                        <LemonSkeleton className="h-24" />
                    </div>
                </div>
            </SceneContent>
        )
    }

    if (!topic) {
        return <NotFound object="interview topic" />
    }

    const pendingCount = totalTargeted - respondedCount
    const questionCount = topic.questions?.length || 0
    const allIdentifiers = [...(topic.interviewee_emails || []), ...(topic.interviewee_distinct_ids || [])]

    return (
        <SceneContent>
            {/* Header */}
            <div className="flex items-start justify-between mb-4 gap-4">
                <div>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        to={urls.userInterviews()}
                        className="mb-1 -ml-2"
                    >
                        All topics
                    </LemonButton>
                    <h1 className="text-2xl font-bold mb-1">{topic.topic}</h1>
                    {topic.agent_context && <p className="text-muted mb-0 text-sm">{topic.agent_context}</p>}
                </div>
                <div className="shrink-0">
                    <LemonButton
                        type="secondary"
                        icon={<IconDownload />}
                        onClick={exportLinksCsv}
                        loading={linksCsvExporting}
                        disabledReason={
                            totalTargeted === 0 ? 'Add interviewees to the topic before exporting links' : undefined
                        }
                        data-attr="export-interview-links-csv"
                        tooltip="Download a CSV with each interviewee's personal interview link, for use in your own email tooling"
                    >
                        Export links (CSV)
                    </LemonButton>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-4 @container @4xl:grid-cols-3">
                {/* Left column */}
                <div className="col-span-2 flex flex-col gap-4">
                    {/* Stats cards */}
                    <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-4">
                        {/* Response rate — hero card */}
                        <div className="col-span-2 rounded-lg border-2 border-success bg-success-highlight p-4 flex items-center justify-between">
                            <div>
                                <div className="text-xs font-semibold uppercase text-success tracking-wide">
                                    Response rate
                                </div>
                                <div className="text-3xl font-bold text-success mt-1">{responseRate}%</div>
                                <div className="text-sm text-muted mt-0.5">
                                    {respondedCount} of {totalTargeted} responded
                                </div>
                            </div>
                            <div className="text-5xl font-bold text-success opacity-20">{respondedCount}</div>
                        </div>

                        <StatCard label="Awaiting response" value={pendingCount} color="warning" />
                        <StatCard label="Questions" value={questionCount} color="muted" />
                    </div>

                    {/* Targeted people list */}
                    <LemonWidget title={`People (${allIdentifiers.length})`}>
                        <div className="divide-y">
                            {intervieweesLoading && interviewees.length === 0 && allIdentifiers.length === 0 ? (
                                <div className="p-4 space-y-3">
                                    <LemonSkeleton.Text className="h-4 w-[60%]" />
                                    <LemonSkeleton.Text className="h-4 w-[40%]" />
                                    <LemonSkeleton.Text className="h-4 w-[50%]" />
                                </div>
                            ) : allIdentifiers.length === 0 ? (
                                <div className="p-4 text-muted text-center">
                                    No people targeted yet. Use PostHog AI to set up targeting and generate interview
                                    links.
                                </div>
                            ) : (
                                allIdentifiers.map((identifier) => (
                                    <PersonRow
                                        key={identifier}
                                        identifier={identifier}
                                        topicId={id}
                                        hasResponded={respondedIdentifiers.has(identifier)}
                                    />
                                ))
                            )}
                        </div>
                    </LemonWidget>
                </div>

                {/* Right column — topic metadata */}
                <div className="col-span-1 flex flex-col gap-4">
                    <LemonWidget title="Details">
                        <div className="p-3 space-y-3">
                            <DetailRow label="Targeting" value={targetingLabel(topic)} />
                            <DetailRow label="Created" value={topic.created_at.split('T')[0]} />
                            <DetailRow
                                label="Owner"
                                value={topic.created_by?.first_name || topic.created_by?.email || '—'}
                            />
                        </div>
                    </LemonWidget>

                    {questionCount > 0 && (
                        <LemonWidget title="Interview questions">
                            <div className="p-3">
                                <LemonMarkdown>
                                    {(topic.questions || []).map((q, i) => `${i + 1}. ${q}`).join('\n')}
                                </LemonMarkdown>
                            </div>
                        </LemonWidget>
                    )}

                    {topic.agent_context && (
                        <LemonWidget title="Agent context">
                            <div className="p-3">
                                <p className="text-sm mb-0">{topic.agent_context}</p>
                            </div>
                        </LemonWidget>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

function StatCard({
    label,
    value,
    color,
}: {
    label: string
    value: number
    color: 'success' | 'warning' | 'primary' | 'muted' | 'danger'
}): JSX.Element {
    const borderColor = {
        success: 'border-success',
        warning: 'border-warning',
        primary: 'border-primary',
        muted: 'border-border',
        danger: 'border-danger',
    }[color]
    const textColor = {
        success: 'text-success',
        warning: 'text-warning',
        primary: 'text-primary',
        muted: 'text-muted',
        danger: 'text-danger',
    }[color]

    return (
        <div className={`rounded-lg border-2 ${borderColor} bg-bg-light p-3`}>
            <div className={`text-2xl font-bold ${textColor}`}>{value}</div>
            <div className="text-xs text-muted font-medium mt-0.5">{label}</div>
        </div>
    )
}

function DetailRow({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex justify-between">
            <span className="text-muted text-sm">{label}</span>
            <span className="text-sm font-medium">{value}</span>
        </div>
    )
}

function PersonRow({
    identifier,
    topicId,
    hasResponded,
}: {
    identifier: string
    topicId: string
    hasResponded: boolean
}): JSX.Element {
    return (
        <Link
            to={urls.userInterviewResponse(topicId, encodeURIComponent(identifier))}
            className="block no-underline text-current"
        >
            <div className="p-3 hover:bg-bg-light transition-colors">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="font-medium text-sm">{identifier}</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <InterviewLinkCopyButton identifier={identifier} topicId={topicId} />
                        {hasResponded ? (
                            <LemonTag type="success" icon={<IconCheck />}>
                                Responded
                            </LemonTag>
                        ) : (
                            <LemonTag type="default" icon={<IconClock />}>
                                Awaiting
                            </LemonTag>
                        )}
                        <IconChevronRight className="text-muted" />
                    </div>
                </div>
            </div>
        </Link>
    )
}
