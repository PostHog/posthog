import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode } from '~/queries/schema/schema-general'

export const ContentAutopilotOpenInsightButton = ({
    query,
    'data-attr': dataAttr,
}: {
    query: DataVisualizationNode | DataTableNode
    'data-attr': string
}): JSX.Element => (
    <LemonButton
        size="small"
        icon={<IconOpenInNew />}
        to={urls.insightNew({ query })}
        targetBlank
        tooltip="Open as insight"
        aria-label="Open as insight"
        data-attr={dataAttr}
    />
)
