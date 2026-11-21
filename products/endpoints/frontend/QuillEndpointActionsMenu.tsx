import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconEllipsis, IconPause, IconPlay, IconPulse, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, EndpointType } from '~/types'

import { endpointLogic } from './endpointLogic'

export function QuillEndpointActionsMenu({ endpoint }: { endpoint: EndpointType }): JSX.Element {
    const { confirmDeleteEndpoint, confirmToggleActive, duplicateEndpointFrom } = useActions(endpointLogic)
    const label = `Actions for ${endpoint.name}`

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon-sm"
                        aria-label={label}
                        tooltip={label}
                        data-attr="endpoint-actions"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.endpointsUsage({ endpointFilter: [endpoint.name] }))}
                    data-attr="endpoint-view-usage"
                >
                    <IconPulse />
                    View usage
                </DropdownMenuItem>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <DropdownMenuItem onClick={() => duplicateEndpointFrom(endpoint)} data-attr="endpoint-duplicate">
                        <IconCopy />
                        Duplicate endpoint
                    </DropdownMenuItem>
                </AccessControlAction>
                <DropdownMenuSeparator />
                <AccessControlAction
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <DropdownMenuItem onClick={() => confirmToggleActive(endpoint)} data-attr="endpoint-activate">
                        {endpoint.is_active ? <IconPause /> : <IconPlay />}
                        {endpoint.is_active ? 'Deactivate endpoint' : 'Activate endpoint'}
                    </DropdownMenuItem>
                </AccessControlAction>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() => confirmDeleteEndpoint(endpoint.name)}
                        data-attr="endpoint-delete"
                    >
                        <IconTrash />
                        Delete endpoint
                    </DropdownMenuItem>
                </AccessControlAction>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
