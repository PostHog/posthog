import { IconEllipsis, IconTrash } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export interface QuillSharedMetricActionsProps {
    showDelete: boolean
    userAccessLevel?: AccessControlLevel
    deleteLoading: boolean
    onDelete: () => void
    saveDisabledReason: string | undefined
    saving: boolean
    onSave: () => void
}

export function QuillSharedMetricActions({
    showDelete,
    userAccessLevel,
    deleteLoading,
    onDelete,
    saveDisabledReason,
    saving,
    onSave,
}: QuillSharedMetricActionsProps): JSX.Element {
    return (
        <>
            {showDelete && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button size="icon" aria-label="more" tooltip="More" data-attr="more-button" />}
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-40">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.ExperimentSavedMetric}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={userAccessLevel}
                        >
                            <DropdownMenuItem
                                variant="destructive"
                                data-attr="shared-metric-delete"
                                disabled={deleteLoading}
                                onClick={onDelete}
                            >
                                <IconTrash />
                                Delete
                            </DropdownMenuItem>
                        </AccessControlAction>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            <AccessControlAction
                resourceType={AccessControlResourceType.ExperimentSavedMetric}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={userAccessLevel}
            >
                <Button disabledReason={saveDisabledReason} loading={saving} variant="primary" onClick={onSave}>
                    Save
                </Button>
            </AccessControlAction>
        </>
    )
}
