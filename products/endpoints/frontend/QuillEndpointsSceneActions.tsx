import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconGraph, IconPlus, IconServer } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { insightPickerEndpointModalLogic } from './insightPickerEndpointModalLogic'

export function QuillEndpointsSceneActions(): JSX.Element {
    const { openModal } = useActions(insightPickerEndpointModalLogic)
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Endpoint,
        AccessControlLevel.Editor
    )

    const options = [
        {
            icon: IconServer,
            name: 'SQL-based endpoint',
            description: 'Create an endpoint from a query in the SQL editor.',
            onClick: () => router.actions.push(urls.sqlEditor({ source: 'endpoint' })),
            dataAttr: 'new-endpoint-overlay-hogql',
        },
        {
            icon: IconGraph,
            name: 'Insight-based endpoint',
            description: 'Create an endpoint from a new or existing insight.',
            onClick: openModal,
            dataAttr: 'new-endpoint-overlay-insight',
        },
    ]

    return (
        <DropdownMenu>
            <ButtonGroup>
                <Shortcut
                    name="EndpointsNew"
                    keybind={[keyBinds.new]}
                    intent="New endpoint"
                    interaction="click"
                    scope={Scene.EndpointsScene}
                >
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Endpoint}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <Button
                            variant="primary"
                            render={<LinkPrimitive to={urls.sqlEditor({ source: 'endpoint' })} />}
                            data-attr="new-endpoint-button"
                        >
                            <IconPlus />
                            New
                        </Button>
                    </AccessControlAction>
                </Shortcut>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="primary"
                            size="icon"
                            aria-label="New endpoint options"
                            tooltip="New endpoint options"
                            disabledReason={accessDisabledReason}
                            data-attr="new-endpoint-dropdown"
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
            </ButtonGroup>
            <DropdownMenuContent align="end" className="new-endpoint-overlay">
                {options.map((option) => (
                    <AccessControlAction
                        key={option.name}
                        resourceType={AccessControlResourceType.Endpoint}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <DropdownMenuItem
                            onClick={option.onClick}
                            data-attr={option.dataAttr}
                            data-attr-endpoint-type={option.name}
                            description={option.description}
                        >
                            <option.icon />
                            {option.name}
                        </DropdownMenuItem>
                    </AccessControlAction>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
