import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { workflowLogic } from '../../../workflowLogic'
import { aiTaskInstructionsCompareLogic, findAiTaskPrompt } from './aiTaskInstructionsCompareLogic'
import { InstructionsDiff } from './InstructionsDiff'

// Fills the h-64 result box under the one-line legend, so the editor is the only scroll area in the box.
const DIFF_HEIGHT = 'calc(16rem - 1.25rem - 2px)'

export function AiTaskInstructionsCompare({ actionId }: { actionId: string }): JSX.Element | null {
    const { logicProps, originalWorkflow, workflow, externallyEdited } = useValues(workflowLogic)
    const logic = aiTaskInstructionsCompareLogic({ workflowId: logicProps.id ?? 'new', actionId })
    const {
        isOpen,
        selectedVersion,
        revisionOptions,
        revisionsResponse,
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

    const livePrompt = findAiTaskPrompt(originalWorkflow.actions, actionId)
    const currentPrompt = findAiTaskPrompt(workflow.actions, actionId) ?? ''

    if (!isOpen) {
        return (
            <div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconClock />}
                    // Compared with live, unchanged instructions only say "No differences", so open on a past version.
                    onClick={() => setOpen(true, currentPrompt === livePrompt ? originalWorkflow.version : null)}
                    data-attr="workflow-ai-task-compare-open"
                >
                    Compare instructions with another version
                </LemonButton>
            </div>
        )
    }

    const comparedPrompt = selectedVersion === null ? livePrompt : selectedRevisionPrompt
    const versionName = selectedVersion === null ? 'the live version' : `v${selectedVersion}`
    // The editor's live copy can be older than the list, which loads on each open. A newer version is not
    // past, and listing it would sit beside a stale "Live version" label.
    const pastVersionOptions = revisionOptions.filter((option) => option.value < originalWorkflow.version)

    return (
        <div className="flex flex-col gap-2 rounded border p-2" data-attr="workflow-ai-task-compare">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">Compare instructions with</span>
                <LemonSelect<number | null>
                    size="small"
                    value={selectedVersion}
                    onChange={selectVersion}
                    loading={revisionsResponseLoading && !revisionsResponse}
                    aria-label="Version to compare with"
                    options={[
                        { value: null, label: `Live version (v${originalWorkflow.version})` },
                        ...pastVersionOptions,
                    ]}
                    data-attr="workflow-ai-task-compare-version"
                />
                <LemonButton size="small" type="tertiary" className="ml-auto" onClick={() => setOpen(false)}>
                    Close
                </LemonButton>
            </div>
            {externallyEdited && (
                <span className="text-xs text-warning">
                    This workflow changed elsewhere, so the live version here may be out of date.
                </span>
            )}
            {revisionsResponse && !revisionsLoadFailed && pastVersionOptions.length === 0 && (
                <span className="text-xs text-secondary">
                    No past versions yet. One is saved each time the live workflow changes.
                </span>
            )}
            {revisionsLoadFailed && (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-danger">Couldn't load past versions.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadRevisions()}>
                        Try again
                    </LemonButton>
                </div>
            )}
            {/* A fixed height keeps the Instructions field below in place while the diff follows each keystroke. */}
            <div className="ph-no-capture h-64 overflow-auto">
                {selectedVersion !== null && revisionLoadFailed ? (
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm text-danger">{`Couldn't load ${versionName}.`}</span>
                        <LemonButton size="xsmall" type="secondary" onClick={() => loadRevision(selectedVersion)}>
                            Try again
                        </LemonButton>
                    </div>
                ) : comparedPrompt === undefined ? (
                    <LemonSkeleton className="h-24 w-full" />
                ) : comparedPrompt === null ? (
                    <span className="text-sm text-secondary">{`This AI task step isn't in ${versionName}.`}</span>
                ) : comparedPrompt === currentPrompt ? (
                    <span className="text-sm text-secondary">{`No differences from ${versionName}.`}</span>
                ) : (
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-secondary">
                            {`Removed lines are from ${versionName}. Added lines are in this step now.`}
                        </span>
                        {/* Keeps a failed editor load inside this box, so the rest of the step panel stays usable. */}
                        <ErrorBoundary>
                            <InstructionsDiff before={comparedPrompt} after={currentPrompt} height={DIFF_HEIGHT} />
                        </ErrorBoundary>
                    </div>
                )}
            </div>
        </div>
    )
}
