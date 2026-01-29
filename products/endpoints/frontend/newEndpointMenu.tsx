import { router } from 'kea-router'

import { IconGraph, IconServer } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { urls } from 'scenes/urls'

interface EndpointTypeOption {
    icon: React.ComponentType
    name: string
    description: string
    url: string
}

const ENDPOINT_TYPE_OPTIONS: EndpointTypeOption[] = [
    {
        icon: IconServer,
        name: 'HogQL endpoint',
        description: 'Create an endpoint from a HogQL query in the SQL editor.',
        url: urls.sqlEditor({ outputTab: OutputTab.Endpoint }),
    },
    {
        icon: IconGraph,
        name: 'Insight endpoint',
        description: 'Create an endpoint from a new insight.',
        url: urls.insightNew(),
    },
]

export function OverlayForNewEndpointMenu({ dataAttr }: { dataAttr: string }): JSX.Element {
    return (
        <>
            {ENDPOINT_TYPE_OPTIONS.map((option) => (
                <LemonButton
                    key={option.name}
                    icon={<option.icon />}
                    onClick={() => {
                        router.actions.push(option.url)
                    }}
                    data-attr={dataAttr}
                    data-attr-endpoint-type={option.name}
                    fullWidth
                >
                    <div className="flex flex-col text-sm py-1">
                        <strong>{option.name}</strong>
                        <span className="text-xs font-sans font-normal">{option.description}</span>
                    </div>
                </LemonButton>
            ))}
        </>
    )
}
