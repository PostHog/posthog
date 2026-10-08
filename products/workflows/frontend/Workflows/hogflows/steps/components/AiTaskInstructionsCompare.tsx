import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { InstructionsDiff } from '../../../InstructionsDiff'
import { workflowLogic } from '../../../workflowLogic'
import { aiTaskInstructionsCompareLogic, findAiTaskPrompt } from './aiTaskInstructionsCompareLogic'

export function AiTaskInstructionsCompare({ actionId }: { actionId: string }): JSX.Element | null {
    const { logicProps, originalWorkflow, workflow } = useValues(workflowLogic)
    const logic = aiTaskInstructionsCompareLogic({ workflowId: logicProps.id ?? 'new', actionId })
    const {
        isOpen,
        selectedVersion,
        revisions,
        revisionsResponseLoading,
        revisionsLoadFailed,
        selectedRevisionPrompt,
        revisionLoadFailed,
    } = useValues(logic)
    const { setOpen, selectVersion, loadRevision, loadRevisions } = useActions(logic)

    // The default comparison is with the live version, and only an active workflow runs one.
    if (!originalWorkflow || originalWorkflow.status !== 'active') {
        return null
    }

    if (!isOpen) {
        return (
            <div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconClock />}
                    onClick={() => setOpen(true)}
                    data-attr="workflow-ai-task-compare-open"
                >
                    Compare instructions with another version
                </LemonButton>
            </div>
        )
    }

    const currentPrompt = findAiTaskPrompt(workflow.actions, actionId) ?? ''
    const comparedPrompt =
        selectedVersion === null ? findAiTaskPrompt(originalWorkflow.actions, actionId) : selectedRevisionPrompt
    const versionName = selectedVersion === null ? 'the live version' : `v${selectedVersion}`
    const versionSubject = selectedVersion === null ? 'The live version' : versionName

    return (
        <div className="flex flex-col gap-2 rounded border p-2" data-attr="workflow-ai-task-compare">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">Compare instructions with</span>
                <LemonSelect<number | null>
                    size="small"
                    value={selectedVersion}
                    onChange={selectVersion}
                    loading={revisionsResponseLoading}
                    aria-label="Version to compare with"
                    options={[
                        { value: null, label: `Live version (v${originalWorkflow.version})` },
                        ...revisions
                            .filter((revision) => revision.version !== originalWorkflow.version)
                            .map((revision) => ({
                                value: revision.version,
                                label: `v${revision.version}`,
                                labelInMenu: `v${revision.version} · ${dayjs(revision.created_at).format('MMM D, YYYY')}`,
                            })),
                    ]}
                    data-attr="workflow-ai-task-compare-version"
                />
                <LemonButton size="small" type="tertiary" className="ml-auto" onClick={() => setOpen(false)}>
                    Close
                </LemonButton>
            </div>
            {revisionsLoadFailed && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-danger">Could not load past versions.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadRevisions()}>
                        Try again
                    </LemonButton>
                </div>
            )}
            {/* A fixed height keeps the Instructions field below in place while the diff follows each keystroke. */}
            <div className="h-64 overflow-auto">
                {selectedVersion !== null && revisionLoadFailed ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm text-danger">Could not load {versionName}.</span>
                        <LemonButton size="xsmall" type="secondary" onClick={() => loadRevision(selectedVersion)}>
                            Try again
                        </LemonButton>
                    </div>
                ) : comparedPrompt === undefined ? (
                    <LemonSkeleton className="h-24 w-full" />
                ) : comparedPrompt === null ? (
                    <span className="text-sm text-secondary">
                        {versionSubject} has no AI task instructions for this step.
                    </span>
                ) : comparedPrompt === currentPrompt ? (
                    <span className="text-sm text-secondary">No differences from {versionName}.</span>
                ) : (
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-secondary">
                            Removed lines are from {versionName}. Added lines are the current instructions.
                        </span>
                        {/* Keeps a failed editor load inside this box, so the rest of the step panel stays usable. */}
                        <ErrorBoundary>
                            <InstructionsDiff before={comparedPrompt} after={currentPrompt} />
                        </ErrorBoundary>
                    </div>
                )}
            </div>
        </div>
    )
}
