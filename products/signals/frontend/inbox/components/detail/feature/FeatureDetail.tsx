import { useActions, useValues } from 'kea'
import { lazy, Suspense } from 'react'

import { IconAI, IconArrowLeft, IconClockRewind, IconDocument, IconPencil, IconQuestion } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonTabs,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { featureDetailLogic, FeatureDetailSubTab } from '../../../logics/featureDetailLogic'
import { inboxReportDetailLogic } from '../../../logics/inboxReportDetailLogic'
import { SignalReport, SignalReportArtefact } from '../../../types'
import { SignalReportStatusBadge } from '../../badges/SignalReportStatusBadge'
import { ScoutDetailView } from '../../config/scouts/ScoutDetailView'
import { ArtefactLogList } from '../ArtefactLogList'
import { DetailSection } from '../DetailSection'
import { ReportTasksSection } from '../ReportTasksSection'
import { SuggestedReviewersSection } from '../SuggestedReviewersSection'

// The live conversation+composer surface from the task runner scene. Lazy: it eagerly pulls the whole
// run-surface chunk, which the inbox otherwise avoids (its other embeds use the lazy ReadonlyRunSurface).
const TaskRunChat = lazy(() =>
    import('products/posthog_ai/frontend/scenes/TaskTracker/components/TaskRunChat').then((m) => ({
        default: m.TaskRunChat,
    }))
)

const MARKDOWN_BODY_CLASSES =
    'text-sm text-secondary leading-relaxed break-words [&>*+*]:mt-3 [&_li]:my-1 [&_ul]:my-2 [&_ol]:my-2'

/** The summary body: rendered markdown that swaps to a textarea on click. */
function EditableSummary({ report }: { report: SignalReport }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { editingField, fieldDraft, fieldSaving } = useValues(logic)
    const { startEditingField, setFieldDraft, cancelEditingField, saveField } = useActions(logic)

    if (editingField === 'summary') {
        return (
            <div className="flex flex-col gap-2 rounded border border-accent bg-surface-primary p-3">
                <LemonTextArea
                    value={fieldDraft}
                    onChange={setFieldDraft}
                    minRows={6}
                    placeholder="Describe the feature in markdown…"
                    autoFocus
                />
                <div className="flex items-center justify-end gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={cancelEditingField}
                        disabledReason={fieldSaving ? 'Saving…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" onClick={saveField} loading={fieldSaving}>
                        Save
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div
            className="group relative cursor-text rounded border border-transparent -m-1 p-1 transition-colors hover:border-accent"
            onClick={() => startEditingField('summary', report.summary ?? '')}
        >
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconPencil />}
                className="absolute right-1 top-1 opacity-0 transition-opacity group-hover:opacity-100"
                tooltip="Edit summary"
                onClick={(e) => {
                    e.stopPropagation()
                    startEditingField('summary', report.summary ?? '')
                }}
            />
            {report.summary ? (
                <LemonMarkdown className={MARKDOWN_BODY_CLASSES} disableImages>
                    {report.summary}
                </LemonMarkdown>
            ) : (
                <p className="m-0 text-sm italic text-tertiary">No summary yet. Click to write one.</p>
            )}
        </div>
    )
}

/** One open question: the question text, with an in-place answer surface. */
function OpenQuestionItem({ report, artefact }: { report: SignalReport; artefact: SignalReportArtefact }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { answeringQuestionId, answerDraft, answerSaving } = useValues(logic)
    const { startAnswering, setAnswerDraft, cancelAnswering, saveAnswer } = useActions(logic)

    const questionText = typeof artefact.content?.question === 'string' ? artefact.content.question : ''
    const answering = answeringQuestionId === artefact.id

    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3">
            <LemonMarkdown className="text-sm text-secondary break-words" disableImages>
                {questionText}
            </LemonMarkdown>
            <div className="flex items-center gap-2 text-xs text-tertiary">
                <TZLabel time={artefact.created_at} />
            </div>
            {answering ? (
                <div className="flex flex-col gap-2">
                    <LemonTextArea
                        value={answerDraft}
                        onChange={setAnswerDraft}
                        minRows={2}
                        placeholder="Write your answer…"
                        autoFocus
                    />
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={cancelAnswering}
                            disabledReason={answerSaving ? 'Saving…' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton size="small" type="primary" onClick={saveAnswer} loading={answerSaving}>
                            Answer
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => startAnswering(artefact.id)}
                    className="w-fit"
                >
                    Answer
                </LemonButton>
            )}
        </div>
    )
}

/** An answered question: dimmed, with the answer quoted beneath. */
function AnsweredQuestionItem({ artefact }: { artefact: SignalReportArtefact }): JSX.Element {
    const questionText = typeof artefact.content?.question === 'string' ? artefact.content.question : ''
    const answerText = typeof artefact.content?.answer === 'string' ? artefact.content.answer : ''
    return (
        <div className="flex flex-col gap-1.5 rounded border border-primary bg-surface-primary p-3 opacity-75">
            <div className="flex items-center gap-2">
                {artefact.created_by ? (
                    <LemonTag size="small" type="highlight">
                        Feedback
                    </LemonTag>
                ) : null}
                <LemonTag size="small" type="success">
                    Answered
                </LemonTag>
                <TZLabel time={artefact.updated_at ?? artefact.created_at} className="text-xs text-tertiary" />
            </div>
            <LemonMarkdown className="text-xs text-secondary break-words" disableImages>
                {questionText}
            </LemonMarkdown>
            {answerText && (
                <LemonMarkdown
                    className="text-xs text-tertiary break-words border-l-2 border-primary pl-2"
                    disableImages
                >
                    {answerText}
                </LemonMarkdown>
            )}
        </div>
    )
}

/**
 * A composer that appends a user-attributed `question` artefact — human→agent feedback. Direction
 * is carried by attribution: user-authored questions are answered by agents, agent-authored ones
 * by the user.
 */
function FeatureFeedbackComposer({ report }: { report: SignalReport }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { feedbackDraft, feedbackSaving } = useValues(logic)
    const { setFeedbackDraft, saveFeedback } = useActions(logic)

    return (
        <div className="flex flex-col gap-2">
            <LemonTextArea
                value={feedbackDraft}
                onChange={setFeedbackDraft}
                minRows={2}
                placeholder="Leave feedback for the agents. Add a change of direction, new context, or something to address."
            />
            <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-tertiary">The owner scout acts on and answers it on its next run.</span>
                <LemonButton
                    size="small"
                    type="primary"
                    onClick={saveFeedback}
                    loading={feedbackSaving}
                    disabledReason={!feedbackDraft.trim() ? 'Write some feedback first' : undefined}
                >
                    Add feedback
                </LemonButton>
            </div>
        </div>
    )
}

/** One piece of outstanding user feedback: waiting on an agent, so no answer affordance. */
function OutstandingFeedbackItem({ artefact }: { artefact: SignalReportArtefact }): JSX.Element {
    const questionText = typeof artefact.content?.question === 'string' ? artefact.content.question : ''
    return (
        <div className="flex flex-col gap-1.5 rounded border border-primary bg-surface-primary p-3">
            <div className="flex items-center gap-2">
                <LemonTag size="small" type="caution">
                    Waiting on agent
                </LemonTag>
                <TZLabel time={artefact.created_at} className="text-xs text-tertiary" />
            </div>
            <LemonMarkdown className="text-sm text-secondary break-words" disableImages>
                {questionText}
            </LemonMarkdown>
        </div>
    )
}

/** Status sub-tab: editable summary on the left; questions, feedback, owners, and runs on the right. */
function FeatureStatusTab({ report }: { report: SignalReport }): JSX.Element {
    const { openQuestions, outstandingFeedback, answeredQuestions } = useValues(
        featureDetailLogic({ reportId: report.id, report })
    )

    return (
        <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,80ch)_minmax(22rem,1fr)] gap-5">
            <div className="min-w-0 flex flex-col gap-5">
                <DetailSection icon={<IconDocument />} title="Summary">
                    <EditableSummary report={report} />
                </DetailSection>
            </div>
            <div className="flex flex-col min-w-0 gap-5">
                <DetailSection
                    icon={<IconQuestion />}
                    title="Open questions"
                    rightSlot={
                        <span className="text-[0.6875rem] text-tertiary tabular-nums">{openQuestions.length}</span>
                    }
                >
                    {openQuestions.length > 0 ? (
                        <div className="flex flex-col gap-3">
                            {openQuestions.map((artefact) => (
                                <OpenQuestionItem key={artefact.id} report={report} artefact={artefact} />
                            ))}
                        </div>
                    ) : (
                        <p className="m-0 text-sm italic text-tertiary">
                            No open questions. The agent asks here when it needs your input.
                        </p>
                    )}
                </DetailSection>
                <DetailSection
                    icon={<IconPencil />}
                    title="Outstanding feedback"
                    rightSlot={
                        <span className="text-[0.6875rem] text-tertiary tabular-nums">
                            {outstandingFeedback.length}
                        </span>
                    }
                >
                    <div className="flex flex-col gap-3">
                        {outstandingFeedback.map((artefact) => (
                            <OutstandingFeedbackItem key={artefact.id} artefact={artefact} />
                        ))}
                        <FeatureFeedbackComposer report={report} />
                    </div>
                </DetailSection>
                {answeredQuestions.length > 0 && (
                    <DetailSection
                        icon={<IconQuestion />}
                        title="Answered"
                        collapsible
                        defaultCollapsed
                        rightSlot={
                            <span className="text-[0.6875rem] text-tertiary tabular-nums">
                                {answeredQuestions.length}
                            </span>
                        }
                    >
                        <div className="flex flex-col gap-3">
                            {answeredQuestions.map((artefact) => (
                                <AnsweredQuestionItem key={artefact.id} artefact={artefact} />
                            ))}
                        </div>
                    </DetailSection>
                )}
                <SuggestedReviewersSection report={report} title="Owners" />
                <ReportTasksSection report={report} />
            </div>
        </div>
    )
}

/** Owner sub-tab: the scout that acts on this feature, resolved by its deterministic skill name. */
function FeatureOwnerTab({ report }: { report: SignalReport }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { ownerScoutConfig, ownerScoutConfigLoading } = useValues(logic)

    if (ownerScoutConfigLoading && !ownerScoutConfig) {
        return <LemonSkeleton className="h-24 max-w-[80ch] rounded" />
    }

    if (!ownerScoutConfig) {
        return (
            <div className="max-w-[80ch]">
                <LemonBanner type="info">
                    <div className="flex flex-col gap-1">
                        <span className="font-semibold">No owner yet</span>
                        <span className="text-sm">
                            The owner is a scout that implements, monitors, and improves this feature over time.
                            Finishing planning creates one automatically.
                        </span>
                    </div>
                </LemonBanner>
            </div>
        )
    }

    // The full scout surface (config editing, rollups, run history) embedded in place — same
    // component as /inbox/scouts/:skillName, minus the back link.
    return (
        <div className="flex max-w-[110ch] flex-col min-h-0">
            <ScoutDetailView skillName={ownerScoutConfig.skill_name} embedded />
        </div>
    )
}

/** Feed sub-tab: the full chronological artefact log for the feature, with a feedback composer on top. */
function FeatureFeedTab({ report }: { report: SignalReport }): JSX.Element {
    const { reportArtefacts, reportTasks } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const knownTasks = new Map((reportTasks ?? []).map((entry) => [entry.task.id, entry.task]))

    return (
        <div className="max-w-[100ch] flex flex-col gap-4">
            <div className="rounded border border-primary bg-surface-primary p-3">
                <FeatureFeedbackComposer report={report} />
            </div>
            {reportArtefacts && reportArtefacts.length > 0 ? (
                <ArtefactLogList reportId={report.id} artefacts={reportArtefacts} knownTasks={knownTasks} />
            ) : (
                <p className="m-0 text-sm italic text-tertiary">No activity yet.</p>
            )}
        </div>
    )
}

/** The feature's title: an h1 that swaps to an input on the pencil affordance. */
function EditableTitle({ report }: { report: SignalReport }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { editingField, fieldDraft, fieldSaving } = useValues(logic)
    const { startEditingField, setFieldDraft, cancelEditingField, saveField } = useActions(logic)

    if (editingField === 'title') {
        return (
            <div className="flex items-center gap-2 min-w-0 flex-1">
                <LemonInput
                    value={fieldDraft}
                    onChange={setFieldDraft}
                    placeholder="Feature title"
                    className="flex-1"
                    autoFocus
                    onPressEnter={saveField}
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={cancelEditingField}
                    disabledReason={fieldSaving ? 'Saving…' : undefined}
                >
                    Cancel
                </LemonButton>
                <LemonButton size="small" type="primary" onClick={saveField} loading={fieldSaving}>
                    Save
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="group flex items-center gap-2 min-w-0">
            <h1 className="min-w-0 m-0 break-words text-xl font-bold leading-tight tracking-tight">
                {report.title || 'Untitled feature'}
            </h1>
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconPencil />}
                className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                tooltip="Edit title"
                onClick={() => startEditingField('title', report.title ?? '')}
            />
        </div>
    )
}

/**
 * Initial planning view. The conversation leads while a live feature summary and artefact log show
 * the durable output. Finish planning becomes available once the required context exists.
 */
function FeaturePlanningView({ report }: { report: SignalReport }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { missingForPlanningCompletion, finishingPlanning } = useValues(logic)
    const { finishPlanning } = useActions(logic)
    const { reportArtefacts, primaryTask } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))

    const planningTaskId = primaryTask?.task.id
    const planningRunId = primaryTask?.task.latest_run?.id

    return (
        <div className="@container w-full max-w-[calc(180ch+5rem)] mx-auto px-6 py-5 text-sm flex flex-col flex-1 min-h-0">
            <div className="flex flex-col gap-3.5 mb-4 shrink-0">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={urls.inbox('features')}
                    className="-ml-2 w-fit"
                >
                    Features
                </LemonButton>
                <div className="flex items-start justify-between gap-4">
                    <div className="flex flex-col gap-2 min-w-0">
                        <div className="flex items-center gap-2 min-w-0">
                            <h1 className="min-w-0 m-0 break-words text-xl font-bold leading-tight tracking-tight">
                                {report.title || 'Untitled feature'}
                            </h1>
                            <LemonTag type="warning" size="small">
                                Planning
                            </LemonTag>
                        </div>
                        <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary leading-none select-none">
                            <span className="flex items-center gap-1">
                                <span>Started</span>
                                <TZLabel time={report.created_at} />
                            </span>
                        </div>
                    </div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={finishPlanning}
                        loading={finishingPlanning}
                        disabledReason={
                            missingForPlanningCompletion.length > 0
                                ? `Still needed: ${missingForPlanningCompletion.join(', ')}`
                                : undefined
                        }
                        tooltip={
                            missingForPlanningCompletion.length === 0
                                ? 'Complete planning and activate the feature owner'
                                : undefined
                        }
                    >
                        Finish planning
                    </LemonButton>
                </div>
            </div>

            {/* Chat leads (left, 2/3) — it's the primary surface while planning; the live overview rides along right. */}
            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-5 flex-1 min-h-0">
                <div className="min-w-0 flex flex-col min-h-[480px]">
                    <div className="flex flex-col flex-1 min-h-0 rounded border border-primary bg-surface-primary px-4">
                        {planningTaskId && planningRunId ? (
                            <Suspense fallback={<LemonSkeleton className="my-4 h-24" />}>
                                <TaskRunChat taskId={planningTaskId} runId={planningRunId} />
                            </Suspense>
                        ) : (
                            <div className="flex flex-1 items-center justify-center text-sm text-tertiary">
                                Starting the planning conversation…
                            </div>
                        )}
                    </div>
                </div>
                <div className="min-w-0 flex flex-col gap-5 overflow-y-auto">
                    <DetailSection icon={<IconDocument />} title="Summary">
                        {report.summary ? (
                            <LemonMarkdown className={MARKDOWN_BODY_CLASSES} disableImages>
                                {report.summary}
                            </LemonMarkdown>
                        ) : (
                            <p className="m-0 text-sm italic text-tertiary">
                                No summary yet. Plan the feature with the agent and it will fill this in.
                            </p>
                        )}
                    </DetailSection>
                    <DetailSection icon={<IconClockRewind />} title="Artefacts">
                        {reportArtefacts && reportArtefacts.length > 0 ? (
                            <ArtefactLogList reportId={report.id} artefacts={reportArtefacts} />
                        ) : (
                            <p className="m-0 text-sm italic text-tertiary">Nothing yet.</p>
                        )}
                    </DetailSection>
                </div>
            </div>
        </div>
    )
}

/**
 * Dedicated feature report detail with Status, Owner, and Feed surfaces. Initial planning uses the
 * live conversation view; the same report remains active afterward.
 */
export function FeatureDetail({ report }: { report: SignalReport }): JSX.Element {
    const logic = featureDetailLogic({ reportId: report.id, report })
    const { activeSubTab, isPlanning, isStaged, hasImplementationRun, startingImplementation, promotingFeature } =
        useValues(logic)
    const { setActiveSubTab, startImplementation, promoteFeature } = useActions(logic)

    if (isPlanning) {
        return <FeaturePlanningView report={report} />
    }

    const featurePath = urls.inboxReport('features', report.id)

    const tabs: { key: FeatureDetailSubTab; label: string; content: JSX.Element }[] = [
        { key: 'status', label: 'Status', content: <FeatureStatusTab report={report} /> },
        { key: 'owner', label: 'Owner', content: <FeatureOwnerTab report={report} /> },
        { key: 'feed', label: 'Feed', content: <FeatureFeedTab report={report} /> },
    ]

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <div className="flex flex-col gap-3.5 mb-4">
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={urls.inbox('features')}
                    className="-ml-2 w-fit"
                >
                    Features
                </LemonButton>
                <div className="flex flex-col gap-2 @2xl:flex-row @2xl:items-start @2xl:justify-between @2xl:gap-4">
                    <div className="flex flex-col gap-2 min-w-0 flex-1">
                        <EditableTitle report={report} />
                        <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary leading-none select-none">
                            {isStaged ? (
                                <LemonTag type="highlight">Discovered</LemonTag>
                            ) : (
                                <SignalReportStatusBadge status={report.status} />
                            )}
                            <span className="flex items-center gap-1">
                                <span>Started</span>
                                <TZLabel time={report.created_at} />
                            </span>
                            <span aria-hidden>·</span>
                            <span className="flex items-center gap-1">
                                <span>Last updated</span>
                                <TZLabel time={report.updated_at ?? report.created_at} />
                            </span>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 @2xl:shrink-0">
                        {isStaged ? (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={promoteFeature}
                                loading={promotingFeature}
                            >
                                Promote feature
                            </LemonButton>
                        ) : hasImplementationRun === false ? (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={startImplementation}
                                loading={startingImplementation}
                                tooltip="Start the first implementation pass. A cloud agent reads the feature and builds the latest described work item."
                            >
                                Start implementing
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconLink />}
                            tooltip="Copy a link to this feature"
                            onClick={() =>
                                void copyToClipboard(
                                    `${window.location.origin}${addProjectIdIfMissing(featurePath)}`,
                                    'feature link'
                                )
                            }
                        >
                            Copy link
                        </LemonButton>
                    </div>
                </div>
            </div>

            {isStaged && (
                <LemonBanner type="info" className="mb-4">
                    Promote feature starts a planning session with an agent. Review the feature together, then finish
                    planning to activate its owner scout.
                </LemonBanner>
            )}

            <LemonTabs<FeatureDetailSubTab>
                activeKey={activeSubTab}
                onChange={setActiveSubTab}
                tabs={tabs.map(({ key, label }) => ({
                    key,
                    label:
                        key === 'owner' ? (
                            <span className="flex items-center gap-1.5">
                                <IconAI className="text-sm" />
                                {label}
                            </span>
                        ) : key === 'feed' ? (
                            <span className="flex items-center gap-1.5">
                                <IconClockRewind className="text-sm" />
                                {label}
                            </span>
                        ) : (
                            label
                        ),
                    content: <></>,
                }))}
            />
            <div className="pt-4">{tabs.find((t) => t.key === activeSubTab)?.content}</div>
        </div>
    )
}
