import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { InstructionsDiff } from '../../../InstructionsDiff'
import { workflowLogic } from '../../../workflowLogic'
import { aiTaskInstructionsCompareLogic, findAiTaskPrompt } from './aiTaskInstructionsCompareLogic'

export function AiTaskInstructionsCompare({ actionId }: { actionId: string }): JSX.Element | null {
    const { logicProps, originalWorkflow, workflow } = useValues(workflowLogic)
    const logic = aiTaskInstructionsCompareLogic({ workflowId: logicProps.id ?? 'new', actionId })
    const { isOpen, selectedVersion, revisions, revisionsResponseLoading, selectedRevisionPrompt, revisionLoadFailed } =
        useValues(logic)
    const { setOpen, selectVersion } = useActions(logic)

    // A workflow has versions only once it has gone live.
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
                    Compare with another version
                </LemonButton>
            </div>
        )
    }

    const currentPrompt = findAiTaskPrompt(workflow.actions, actionId) ?? ''
    const comparedPrompt =
        selectedVersion === null ? findAiTaskPrompt(originalWorkflow.actions, actionId) : selectedRevisionPrompt
    const versionName = selectedVersion === null ? 'the live version' : `v${selectedVersion}`

    return (
        <div className="flex flex-col gap-2 rounded border p-2" data-attr="workflow-ai-task-compare">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">Compare instructions with</span>
                <LemonSelect<number | null>
                    size="small"
                    value={selectedVersion}
                    onChange={selectVersion}
                    loading={revisionsResponseLoading}
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
            {revisionLoadFailed ? (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-danger">Could not load {versionName}.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => selectVersion(selectedVersion)}>
                        Try again
                    </LemonButton>
                </div>
            ) : comparedPrompt === undefined ? (
                <LemonSkeleton className="h-24 w-full" />
            ) : comparedPrompt === null ? (
                <span className="text-sm text-secondary">This step has no instructions in {versionName}.</span>
            ) : comparedPrompt === currentPrompt ? (
                <span className="text-sm text-secondary">No differences from {versionName}.</span>
            ) : (
                <InstructionsDiff before={comparedPrompt} after={currentPrompt} />
            )}
        </div>
    )
}
