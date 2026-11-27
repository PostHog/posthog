import { Button } from '@posthog/quill'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DataTableNode, DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'

import { insightQuery } from './promptReportQueries'

/** Opens the tile's query as a new insight, where it can be saved and added to a dashboard. */
export const ContentAutopilotOpenInsightButton = ({
    query,
    'data-attr': dataAttr,
}: {
    query: DataVisualizationNode | DataTableNode | InsightVizNode
    'data-attr': string
}): JSX.Element => (
    <Button
        nativeButton={false}
        render={<LinkPrimitive to={urls.insightNew({ query: insightQuery(query) })} target="_blank" />}
        tooltip="Open as a new insight to save it or add it to a dashboard"
        data-attr={dataAttr}
    >
        <IconOpenInNew />
        Open as insight
    </Button>
)
