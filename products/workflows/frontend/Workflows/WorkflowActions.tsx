import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { Button, Separator } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { HogFlowManualTriggerButton } from './hogflows/HogFlowManualTriggerButton'
import { QuillWorkflowSaveActions } from './QuillWorkflowSaveActions'
import { workflowTemplateLogic } from './templates/workflowTemplateLogic'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps } from './workflowSceneLogic'
import { parseWorkflowTriggerPrefill, TRIGGER_PREFILL_PARAM } from './workflowTriggerPrefill'

export function WorkflowActions(props: WorkflowSceneLogicProps): JSX.Element {
    const {
        workflow,
        hasUnsavedChanges,
        hasStagedDraft,
        draftActionPending,
        isWorkflowSubmitting,
        workflowHasErrors,
        workflowUserAccessLevel,
        publishDisabledReason,
        discardDisabledReason,
        showDraftActions,
    } = useValues(workflowLogic)
    const { saveWorkflowPartial, submitWorkflow, discardChanges, publishDraft, discardDraft } =
        useActions(workflowLogic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined
    const templateId = searchParams.templateId as string | undefined
    const { showSaveAsTemplateModal } = useActions(workflowTemplateLogic({ ...props, editTemplateId }))

    const isSavedWorkflow = props.id && props.id !== 'new'
    const isCreatedFromTemplate = props.id === 'new' && !!templateId
    const isCreatedFromLink = props.id === 'new' && !!parseWorkflowTriggerPrefill(searchParams[TRIGGER_PREFILL_PARAM])
    const isManualWorkflow = ['manual', 'batch'].includes(workflow?.trigger?.type || '')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const [displayStatus, setDisplayStatus] = useState(workflow?.status)
    const [isTransitioning, setIsTransitioning] = useState(false)
    const prevStatusRef = useRef(workflow?.status)
    useEffect(() => {
        // Only transition if status actually changed (not on initial mount)
        if (workflow?.status !== displayStatus && prevStatusRef.current !== undefined) {
            setIsTransitioning(true)
            const timer = setTimeout(() => {
                setDisplayStatus(workflow?.status)
                setIsTransitioning(false)
            }, 150)
            prevStatusRef.current = workflow?.status
            return () => clearTimeout(timer)
        } else if (workflow?.status !== displayStatus) {
            // On initial mount, just set it without transition
            setDisplayStatus(workflow?.status)
            prevStatusRef.current = workflow?.status
        }
    }, [workflow?.status, displayStatus])

    return (
        <>
            {isManualWorkflow && <HogFlowManualTriggerButton {...props} />}
            {isSavedWorkflow && (
                <>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Workflow}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={workflowUserAccessLevel ?? undefined}
                    >
                        {todayRailNav ? (
                            <Button
                                variant={displayStatus === 'active' ? 'primary' : 'outline'}
                                // Stays clickable when steps have errors: the attempt is what
                                // reveals the per-field messages, and saveWorkflowPartial
                                // guards the actual enable with a toast.
                                onClick={() =>
                                    saveWorkflowPartial({
                                        status: workflow?.status === 'draft' ? 'active' : 'draft',
                                    })
                                }
                                disabledReason={hasUnsavedChanges ? 'Save changes first' : undefined}
                                className="transition-colors duration-300 ease-in-out"
                                data-attr="workflow-launch"
                            >
                                <span
                                    className={`inline-block transition-opacity duration-300 ease-in-out ${
                                        isTransitioning ? 'opacity-0' : 'opacity-100'
                                    }`}
                                >
                                    {displayStatus === 'draft' ? 'Enable' : 'Disable'}
                                </span>
                            </Button>
                        ) : (
                            <LemonButton
                                type={displayStatus === 'active' ? 'primary' : 'secondary'}
                                // Stays clickable when steps have errors: the attempt is what
                                // reveals the per-field messages, and saveWorkflowPartial
                                // guards the actual enable with a toast.
                                onClick={() =>
                                    saveWorkflowPartial({
                                        status: workflow?.status === 'draft' ? 'active' : 'draft',
                                    })
                                }
                                size="small"
                                disabledReason={hasUnsavedChanges ? 'Save changes first' : undefined}
                                className="transition-colors duration-300 ease-in-out"
                                data-attr="workflow-launch"
                            >
                                <span
                                    className={`inline-block transition-opacity duration-300 ease-in-out ${
                                        isTransitioning ? 'opacity-0' : 'opacity-100'
                                    }`}
                                >
                                    {displayStatus === 'draft' ? 'Enable' : 'Disable'}
                                </span>
                            </LemonButton>
                        )}
                    </AccessControlAction>
                    {todayRailNav ? <Separator orientation="vertical" /> : <LemonDivider vertical />}
                </>
            )}
            {todayRailNav ? (
                <QuillWorkflowSaveActions
                    hasUnsavedChanges={hasUnsavedChanges}
                    hasStagedDraft={hasStagedDraft}
                    showDraftActions={showDraftActions}
                    editTemplateId={editTemplateId}
                    isWorkflowSubmitting={isWorkflowSubmitting}
                    draftActionPending={draftActionPending}
                    saveDisabledReason={
                        workflowHasErrors
                            ? 'Some fields still need work'
                            : isCreatedFromTemplate || isCreatedFromLink
                              ? undefined
                              : hasUnsavedChanges
                                ? undefined
                                : 'No changes to save'
                    }
                    publishDisabledReason={publishDisabledReason}
                    discardDisabledReason={discardDisabledReason}
                    saveLabel={
                        props.id === 'new' ? 'Create as draft' : workflow?.status === 'active' ? 'Save draft' : 'Save'
                    }
                    saveUserAccessLevel={props.id === 'new' ? undefined : (workflowUserAccessLevel ?? undefined)}
                    workflowUserAccessLevel={workflowUserAccessLevel ?? undefined}
                    onDiscardChanges={() => discardChanges()}
                    onUpdateTemplate={showSaveAsTemplateModal}
                    onSave={submitWorkflow}
                    onPublish={() => publishDraft()}
                    onDiscardDraft={() => discardDraft()}
                />
            ) : (
                <>
                    {hasUnsavedChanges && (
                        <LemonButton
                            data-attr="discard-workflow-changes"
                            type="secondary"
                            onClick={() => discardChanges()}
                            size="small"
                        >
                            Clear changes
                        </LemonButton>
                    )}
                    {editTemplateId ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={showSaveAsTemplateModal}
                            loading={isWorkflowSubmitting}
                        >
                            Update template
                        </LemonButton>
                    ) : (
                        // Both buttons hold a fixed slot for the whole edit. Auto-save used to
                        // swap this group between "Save draft" and "Publish" every few seconds,
                        // which moved a different action under a pointer that had not left the
                        // button.
                        <>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Workflow}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={
                                    props.id === 'new' ? undefined : (workflowUserAccessLevel ?? undefined)
                                }
                            >
                                <LemonButton
                                    data-attr="workflow-save"
                                    type={hasStagedDraft && !hasUnsavedChanges ? 'secondary' : 'primary'}
                                    size="small"
                                    htmlType="submit"
                                    form="workflow"
                                    onClick={submitWorkflow}
                                    loading={isWorkflowSubmitting}
                                    disabledReason={
                                        workflowHasErrors
                                            ? 'Some fields still need work'
                                            : isCreatedFromTemplate || isCreatedFromLink
                                              ? undefined
                                              : hasUnsavedChanges
                                                ? undefined
                                                : 'No changes to save'
                                    }
                                >
                                    {props.id === 'new'
                                        ? 'Create as draft'
                                        : workflow?.status === 'active'
                                          ? 'Save draft'
                                          : 'Save'}
                                </LemonButton>
                            </AccessControlAction>
                            {showDraftActions && (
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Workflow}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                                >
                                    <LemonButton
                                        data-attr="workflow-publish"
                                        type={hasStagedDraft && !hasUnsavedChanges ? 'primary' : 'secondary'}
                                        size="small"
                                        onClick={() => publishDraft()}
                                        loading={draftActionPending === 'publish'}
                                        disabledReason={publishDisabledReason}
                                        // Discarding is rare and destructive, so it sits in the
                                        // menu rather than next to the button a person aims for.
                                        sideAction={{
                                            'data-attr': 'workflow-draft-actions',
                                            'aria-label': 'More draft actions',
                                            dropdown: {
                                                placement: 'bottom-end',
                                                overlay: (
                                                    <LemonMenuOverlay
                                                        items={[
                                                            {
                                                                label: 'Discard draft',
                                                                icon: <IconTrash />,
                                                                status: 'danger',
                                                                onClick: () => discardDraft(),
                                                                disabledReason: discardDisabledReason,
                                                                'data-attr': 'workflow-discard-draft',
                                                            },
                                                        ]}
                                                    />
                                                ),
                                            },
                                        }}
                                    >
                                        Publish
                                    </LemonButton>
                                </AccessControlAction>
                            )}
                        </>
                    )}
                </>
            )}
        </>
    )
}
