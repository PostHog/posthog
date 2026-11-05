import { IconBug } from '@posthog/icons'
import { Button, Label, Switch, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export interface QuillEndpointHeaderActionsProps {
    showDebugToggle: boolean
    debugInfoExpanded: boolean
    setDebugInfoExpanded: (expanded: boolean) => void
    endpointLoaded: boolean
    updatingEndpoint: boolean
    hasChanges: boolean
    hasQueryChange: boolean
    targetVersion: number | undefined
    onDiscardChanges: () => void
    onSave: () => void
}

export function QuillEndpointHeaderActions({
    showDebugToggle,
    debugInfoExpanded,
    setDebugInfoExpanded,
    endpointLoaded,
    updatingEndpoint,
    hasChanges,
    hasQueryChange,
    targetVersion,
    onDiscardChanges,
    onSave,
}: QuillEndpointHeaderActionsProps): JSX.Element {
    return (
        <>
            {showDebugToggle && (
                <Tooltip>
                    <TooltipTrigger render={<div className="flex items-center gap-2" />}>
                        <Switch
                            id="endpoint-debug-info"
                            checked={debugInfoExpanded}
                            onCheckedChange={setDebugInfoExpanded}
                        />
                        <Label htmlFor="endpoint-debug-info" className="inline-flex items-center gap-1">
                            <IconBug />
                            Debug info
                        </Label>
                    </TooltipTrigger>
                    <TooltipContent>Visible to staff (and during impersonation) only</TooltipContent>
                </Tooltip>
            )}
            {endpointLoaded && (
                <Button
                    variant="outline"
                    onClick={onDiscardChanges}
                    disabledReason={!hasChanges ? 'No changes to discard' : undefined}
                >
                    Discard changes
                </Button>
            )}
            <AccessControlAction
                resourceType={AccessControlResourceType.Endpoint}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Button
                    variant="primary"
                    onClick={onSave}
                    loading={updatingEndpoint}
                    disabledReason={
                        !endpointLoaded
                            ? 'Endpoint not loaded'
                            : updatingEndpoint
                              ? 'Update in progress'
                              : !hasChanges
                                ? 'No changes to save'
                                : hasQueryChange && targetVersion
                                  ? 'Query can only be changed when on the latest version'
                                  : undefined
                    }
                >
                    Save changes
                </Button>
            </AccessControlAction>
        </>
    )
}
