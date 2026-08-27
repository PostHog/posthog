import { LemonButton } from '@posthog/lemon-ui'

import { IconAreaChart } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import type {
    ExperimentFunnelsQueryResponse,
    ExperimentTrendsQueryResponse,
    InsightVizNode,
} from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightQueryNode } from '~/queries/schema/schema-general'

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyExploreButton({
    result,
    size = 'small',
}: {
    result: ExperimentTrendsQueryResponse | ExperimentFunnelsQueryResponse | null
    size?: 'xsmall' | 'small' | 'large'
}): JSX.Element {
    if (!result) {
        return <></>
    }

    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: (result.kind === NodeKind.ExperimentTrendsQuery
            ? result.count_query
            : result.funnels_query) as InsightQueryNode,
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size={size}
            type="primary"
            icon={<IconAreaChart />}
            to={urls.insightNew({ query })}
            targetBlank
        >
            Explore as Insight
        </LemonButton>
    )
}
