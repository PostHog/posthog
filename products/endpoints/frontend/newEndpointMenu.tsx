import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconGraph, IconServer } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { insightPickerEndpointModalLogic } from './insightPickerEndpointModalLogic'

interface EndpointTypeOption {
    icon: React.ComponentType
    name: string
    description: string
    onClick: () => void
    dataAttr: string
}

export function OverlayForNewEndpointMenu(): JSX.Element {
    const { openModal } = useActions(insightPickerEndpointModalLogic)

    const options: EndpointTypeOption[] = [
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
        <>
            {options.map((option) => (
                <AccessControlAction
                    key={option.name}
                    resourceType={AccessControlResourceType.Endpoint}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        icon={<option.icon />}
                        onClick={option.onClick}
                        data-attr={option.dataAttr}
                        data-attr-endpoint-type={option.name}
                        fullWidth
                    >
                        <div className="flex flex-col text-sm py-1">
                            <strong>{option.name}</strong>
                            <span className="text-xs font-sans font-normal">{option.description}</span>
                        </div>
                    </LemonButton>
                </AccessControlAction>
            ))}
        </>
    )
}
