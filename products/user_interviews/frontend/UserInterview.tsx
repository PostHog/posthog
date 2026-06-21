import { useActions, useValues } from 'kea'

import {
    IconArrowLeft,
    IconCheck,
    IconChevronRight,
    IconClock,
    IconCopy,
    IconDownload,
    IconEye,
    IconFlask,
} from '@posthog/icons'
import { LemonButton, LemonModal, LemonSkeleton, LemonTag, LemonWidget } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import type { PreviewInviteResultApi, TestInterviewLinkApi, UserInterviewTopicApi } from './generated/api.schemas'
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
        testLink,
        testLinkLoading,
        previewInviteIdentifier,
        invitePreview,
        invitePreviewLoading,
    } = useValues(userInterviewLogic)
    const { exportLinksCsv, loadTestLink, openInvitePreview, closeInvitePreview } = useActions(userInterviewLogic)

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
    // Responded interviewees first (grouped together), awaiting ones below — stable within each group.
    const orderedIdentifiers = [...allIdentifiers].sort(
        (a, b) => Number(respondedIdentifiers.has(b)) - Number(respondedIdentifiers.has(a))
    )

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

                    <TestInterviewWidget
                        testLink={testLink}
                        testLinkLoading={testLinkLoading}
                        onRefresh={loadTestLink}
                    />

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
                                orderedIdentifiers.map((identifier) => (
                                    <PersonRow
                                        key={identifier}
                                        identifier={identifier}
                                        topicId={id}
                                        hasResponded={respondedIdentifiers.has(identifier)}
                                        onPreview={() => openInvitePreview(identifier)}
                                        previewLoading={previewInviteIdentifier === identifier && invitePreviewLoading}
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

            <InvitePreviewModal
                isOpen={previewInviteIdentifier !== null}
                onClose={closeInvitePreview}
                preview={invitePreview}
                loading={invitePreviewLoading}
            />
        </SceneContent>
    )
}

export function InvitePreviewModal({
    isOpen,
    onClose,
    preview,
    loading,
}: {
    isOpen: boolean
    onClose: () => void
    preview: PreviewInviteResultApi | null
    loading: boolean
}): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Invite email preview" width="90vw">
            {/* Gate on `loading` alone (not `loading && !preview`): while a newly opened person's
                preview loads, kea-loaders still holds the previous person's value, so keying off
                `loading` shows the skeleton instead of the stale email. */}
            {loading ? (
                <div className="space-y-3 h-[70vh]">
                    <LemonSkeleton.Text className="h-4 w-[50%]" />
                    <LemonSkeleton className="h-[60vh]" />
                </div>
            ) : preview ? (
                <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1">
                        <div className="text-xs font-semibold uppercase text-muted tracking-wide">Subject</div>
                        <div className="text-sm font-medium">{preview.subject}</div>
                        <div className="text-sm text-muted">
                            To {preview.user_name}
                            {preview.email ? ` <${preview.email}>` : ''}
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                            {!preview.emailable && <LemonTag type="warning">No email address — can't be sent</LemonTag>}
                            {preview.is_preview_link && (
                                <LemonTag type="default">Link is a placeholder until invites are sent</LemonTag>
                            )}
                        </div>
                    </div>
                    <iframe
                        srcDoc={preview.html}
                        sandbox=""
                        title="Invite email preview"
                        className="w-full h-[70vh] border rounded"
                    />
                </div>
            ) : (
                <div className="text-muted h-[70vh]">Couldn't load the preview. Try again.</div>
            )}
        </LemonModal>
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

function TestInterviewWidget({
    testLink,
    testLinkLoading,
    onRefresh,
}: {
    testLink: TestInterviewLinkApi | null
    testLinkLoading: boolean
    onRefresh: () => void
}): JSX.Element {
    const interviewUrl = testLink?.interview_url
    const latest = testLink?.latest_test_interview ?? null

    const handleCopy = (): void => {
        if (interviewUrl) {
            void copyToClipboard(interviewUrl, 'test interview link')
        }
    }

    return (
        <LemonWidget
            title={
                <span className="flex items-center gap-2">
                    <IconFlask />
                    <span>Test interview</span>
                    <LemonTag type="warning">No real user needed</LemonTag>
                </span>
            }
        >
            <div className="p-3 space-y-3">
                <p className="text-muted text-sm mb-0">
                    Open this link to try the AI voice interview yourself — your test calls are kept separate from the
                    targeted interviewees and the most recent one appears below.
                </p>
                {testLinkLoading && !testLink ? (
                    <LemonSkeleton.Text className="h-4 w-[80%]" />
                ) : interviewUrl ? (
                    <div className="flex items-center gap-2">
                        <Link to={interviewUrl} target="_blank" className="text-sm font-mono break-all">
                            {interviewUrl}
                        </Link>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconCopy />}
                            onClick={handleCopy}
                            tooltip="Copy test interview link"
                        />
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={onRefresh}
                            loading={testLinkLoading}
                            tooltip="Refresh test interview state"
                        >
                            Refresh
                        </LemonButton>
                    </div>
                ) : (
                    <p className="text-danger text-sm mb-0">Couldn't load the test link. Try refreshing the page.</p>
                )}
                <div>
                    <div className="text-xs font-semibold uppercase text-muted tracking-wide mb-1">
                        Latest test transcript
                    </div>
                    {latest ? (
                        <div className="text-sm space-y-2">
                            <div className="text-muted">
                                Recorded {dayjs(latest.completed_at).format('MMM D, YYYY [at] HH:mm')}
                            </div>
                            {latest.summary ? (
                                <div>
                                    <div className="text-xs font-semibold uppercase text-muted tracking-wide mb-1">
                                        Summary
                                    </div>
                                    <LemonMarkdown>{latest.summary}</LemonMarkdown>
                                </div>
                            ) : null}
                            {latest.transcript ? (
                                <details>
                                    <summary className="cursor-pointer text-xs uppercase text-muted tracking-wide">
                                        Full transcript
                                    </summary>
                                    <pre className="text-xs whitespace-pre-wrap mt-2">{latest.transcript}</pre>
                                </details>
                            ) : null}
                            {!latest.summary && !latest.transcript ? (
                                <div className="text-muted">
                                    The most recent test call completed but no transcript or summary was delivered.
                                </div>
                            ) : null}
                        </div>
                    ) : (
                        <div className="text-sm text-muted">No test call has completed yet for this topic.</div>
                    )}
                </div>
            </div>
        </LemonWidget>
    )
}

function PersonRow({
    identifier,
    topicId,
    hasResponded,
    onPreview,
    previewLoading,
}: {
    identifier: string
    topicId: string
    hasResponded: boolean
    onPreview: () => void
    previewLoading: boolean
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
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            icon={<IconEye />}
                            loading={previewLoading}
                            onClick={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                onPreview()
                            }}
                            data-attr="user-interview-preview-invite"
                            tooltip="Preview the invite email this person would receive"
                        />
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
