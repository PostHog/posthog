import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'

/** Opens the tile's query as a new insight, where it can be saved and added to a dashboard. */
export const ContentAutopilotOpenInsightButton = ({
    query,
    'data-attr': dataAttr,
}: {
    query: DataVisualizationNode | DataTableNode | InsightVizNode
    'data-attr': string
}): JSX.Element => (
    <LemonButton
        size="small"
        icon={<IconOpenInNew />}
        to={urls.insightNew({ query })}
        targetBlank
        tooltip="Open as a new insight to save it or add it to a dashboard"
        data-attr={dataAttr}
    >
        Open as insight
    </LemonButton>
)
