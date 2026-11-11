import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'

import { InsightType } from '~/types'

import { AlertDeletionWarning } from 'products/alerts/frontend/components/AlertDeletionWarning'
import { insightNavLogic } from 'products/product_analytics/frontend/insights/InsightNav/insightNavLogic'

import { QuillInsightsNav } from './QuillInsightsNav'

export function InsightsNav(): JSX.Element {
    const { insightProps, insight } = useValues(insightLogic)
    const { activeView, tabs } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const onChange = (newKey: InsightType): void => {
        posthog.capture('insight type tab clicked', { insight_type: newKey, previous_type: activeView })
        setActiveView(newKey)
    }

    return (
        <>
            {insight.short_id && <AlertDeletionWarning />}
            {todayRailNav ? (
                <QuillInsightsNav tabs={tabs} activeView={activeView} onChange={onChange} />
            ) : (
                <LemonTabs
                    activeKey={activeView}
                    onChange={onChange}
                    tabs={tabs.map(({ label, type, dataAttr, beta }) => ({
                        key: type,
                        label: (
                            <Link to={INSIGHT_TYPE_URLS[type]} preventClick data-attr={dataAttr}>
                                <Tooltip
                                    placement="top"
                                    title={
                                        INSIGHT_TYPES_METADATA[type].tooltipDescription ||
                                        INSIGHT_TYPES_METADATA[type].description
                                    }
                                    docLink={INSIGHT_TYPES_METADATA[type].tooltipDocLink}
                                >
                                    <span>
                                        {label}
                                        {beta && (
                                            <>
                                                {' '}
                                                <LemonTag type="warning">BETA</LemonTag>
                                            </>
                                        )}
                                    </span>
                                </Tooltip>
                            </Link>
                        ),
                    }))}
                />
            )}
        </>
    )
}
