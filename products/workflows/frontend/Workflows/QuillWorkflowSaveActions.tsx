import { IconChevronDown, IconTrash } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

// Module-level so AccessControlAction sees a stable element type and reconciles instead of
// remounting; an inline child would close the draft menu whenever autosave re-rendered the header.
function PublishActions({
    isPrimary,
    draftActionPending,
    publishDisabledReason,
    discardDisabledReason,
    disabledReason,
    onPublish,
    onDiscardDraft,
}: {
    isPrimary: boolean
    draftActionPending: string | null
    publishDisabledReason: string | null | undefined
    discardDisabledReason: string | null | undefined
    disabledReason?: string | null
    onPublish: () => void
    onDiscardDraft: () => void
}): JSX.Element {
    const variant = isPrimary ? 'primary' : 'outline'
    return (
        <ButtonGroup>
            <Button
                data-attr="workflow-publish"
                variant={variant}
                onClick={onPublish}
                loading={draftActionPending === 'publish'}
                disabledReason={publishDisabledReason ?? disabledReason}
            >
                Publish
            </Button>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant={variant}
                            size="icon"
                            aria-label="More draft actions"
                            tooltip="More draft actions"
                            data-attr="workflow-draft-actions"
                            disabledReason={disabledReason}
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem
                        variant="destructive"
                        disabledReason={discardDisabledReason}
                        onClick={onDiscardDraft}
                        data-attr="workflow-discard-draft"
                    >
                        <IconTrash />
                        Discard draft
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </ButtonGroup>
    )
}

export function QuillWorkflowSaveActions({
    hasUnsavedChanges,
    hasStagedDraft,
    showDraftActions,
    editTemplateId,
    isWorkflowSubmitting,
    draftActionPending,
    saveDisabledReason,
    publishDisabledReason,
    discardDisabledReason,
    saveLabel,
    saveUserAccessLevel,
    workflowUserAccessLevel,
    onDiscardChanges,
    onUpdateTemplate,
    onSave,
    onPublish,
    onDiscardDraft,
}: {
    hasUnsavedChanges: boolean
    hasStagedDraft: boolean
    showDraftActions: boolean
    editTemplateId: string | undefined
    isWorkflowSubmitting: boolean
    draftActionPending: string | null
    saveDisabledReason: string | undefined
    publishDisabledReason: string | null | undefined
    discardDisabledReason: string | null | undefined
    saveLabel: string
    saveUserAccessLevel: AccessControlLevel | undefined
    workflowUserAccessLevel: AccessControlLevel | undefined
    onDiscardChanges: () => void
    onUpdateTemplate: () => void
    onSave: () => void
    onPublish: () => void
    onDiscardDraft: () => void
}): JSX.Element {
    const publishIsPrimary = hasStagedDraft && !hasUnsavedChanges
    return (
        <>
            {hasUnsavedChanges && (
                <Button data-attr="discard-workflow-changes" variant="outline" onClick={onDiscardChanges}>
                    Clear changes
                </Button>
            )}
            {editTemplateId ? (
                <Button variant="primary" onClick={onUpdateTemplate} loading={isWorkflowSubmitting}>
                    Update template
                </Button>
            ) : (
                <>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Workflow}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={saveUserAccessLevel}
                    >
                        <Button
                            data-attr="workflow-save"
                            variant={publishIsPrimary ? 'outline' : 'primary'}
                            type="submit"
                            form="workflow"
                            onClick={onSave}
                            loading={isWorkflowSubmitting}
                            disabledReason={saveDisabledReason}
                        >
                            {saveLabel}
                        </Button>
                    </AccessControlAction>
                    {showDraftActions && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={workflowUserAccessLevel}
                        >
                            <PublishActions
                                isPrimary={publishIsPrimary}
                                draftActionPending={draftActionPending}
                                publishDisabledReason={publishDisabledReason}
                                discardDisabledReason={discardDisabledReason}
                                onPublish={onPublish}
                                onDiscardDraft={onDiscardDraft}
                            />
                        </AccessControlAction>
                    )}
                </>
            )}
        </>
    )
}
