import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useValues } from 'kea'

import { Button, Card, CardContent, Text } from '@posthog/quill'

import { AccessDenied } from 'lib/components/AccessDenied'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { Link } from 'lib/lemon-ui/Link'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightModals } from 'scenes/insights/InsightModals'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getInsightIconTypeFromQuery } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import type { Node } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { InsightShortId } from '~/types'

import { ChartSettingsPopover } from './chartSettings/ChartSettingsPopover'
import { ChartTypeAccordion } from './chartTypes/ChartTypeAccordion'
import { ChartTypePopover } from './chartTypes/ChartTypePopover'
import { InsightDataChecks } from './dataChecks/InsightDataChecks'
import { FunnelViewMenu } from './funnel/FunnelViewMenu'
import { InsightAdvancedMenu } from './InsightAdvancedMenu'
import { InsightDraftActions } from './InsightDraftActions'
import { InsightKindMenu } from './InsightKindMenu'
import { DashboardFilterMark } from './sentence/DashboardFilterMark'
import { InsightSentence } from './sentence/InsightSentence'

export interface QuillInsightSceneProps {
    insightId: InsightShortId | 'new'
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

export function QuillInsightScene({ insightId, attachTo }: QuillInsightSceneProps): JSX.Element | null {
    const { insight, filtersOverride, variablesOverride, hasOverrides, dashboardId } = useValues(insightSceneLogic)
    const { currentTeamId } = useValues(teamLogic)

    const logic = insightLogic({
        dashboardItemId: insightId || 'new',
        dashboardId: dashboardId ?? undefined,
        cachedInsight: hasOverrides && insight?.short_id === insightId ? insight : null,
        filtersOverride,
        variablesOverride,
    })
    const { insightProps, accessDeniedToInsight, insightLoading, insightName } = useValues(logic)
    const { query } = useValues(insightDataLogic(insightProps))
    const { setQuery } = useActions(insightDataLogic(insightProps))
    const { zoomDateRange } = useActions(insightVizDataLogic(insightProps))

    useFileSystemLogView({
        type: 'insight',
        ref: insight?.short_id,
        enabled: Boolean(currentTeamId && insight?.short_id && insight?.saved && !accessDeniedToInsight),
    })

    useAttachedLogic(logic, attachTo)
    useAttachedLogic(insightDataLogic(insightProps), attachTo)

    const setSceneQuery = (next: Node | ((current: Node) => Node), isSourceUpdate?: boolean): void => {
        const node = typeof next === 'function' ? (query ? next(query) : null) : next
        if (!isInsightVizNode(node) || isSourceUpdate) {
            setQuery(node)
        }
    }

    if (accessDeniedToInsight) {
        return <AccessDenied object="insight" />
    }

    if (!insight?.query) {
        return null
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightModals insightLogicProps={insightProps} />
            <SceneContent data-attr="quill-insight-scene">
                <SceneTitleSection
                    name={insightName}
                    nameSuffix={<InsightKindMenu insightProps={insightProps} />}
                    description={insight.description || null}
                    resourceType={{ type: getInsightIconTypeFromQuery(query) }}
                    isLoading={insightLoading && !insight.id}
                    actions={
                        <div className="flex flex-wrap items-center gap-2">
                            <InsightDataChecks insightProps={insightProps} />
                            <InsightDraftActions insightProps={insightProps} />
                            <InsightAdvancedMenu insightProps={insightProps} />
                        </div>
                    }
                />
                <InsightSentence
                    insightProps={insightProps}
                    trailing={
                        <div className="flex shrink-0 items-center gap-2">
                            <FunnelViewMenu insightProps={insightProps} />
                            <ChartTypePopover insightProps={insightProps} />
                            <ChartSettingsPopover insightProps={insightProps} />
                        </div>
                    }
                />
                {hasOverrides && insightId !== 'new' && (
                    <div className="flex flex-wrap items-center gap-2">
                        <DashboardFilterMark />
                        <Text size="sm" variant="muted" render={<span />}>
                            Set by the dashboard's filters, not the saved insight.
                        </Text>
                        <Button
                            variant="outline"
                            size="sm"
                            render={<Link to={urls.insightView(insightId, dashboardId ?? undefined)} />}
                            data-attr="quill-insight-show-saved"
                        >
                            Show the saved insight
                        </Button>
                    </div>
                )}
                {/* The chart keeps its own margins, so the card adds no padding of its own. */}
                <Card flush className="pt-0">
                    <CardContent>
                        <Query
                            attachTo={attachTo}
                            query={
                                isInsightVizNode(query)
                                    ? {
                                          ...query,
                                          full: false,
                                          showHeader: false,
                                          showTable: false,
                                          showCorrelationTable: false,
                                          showLastComputation: false,
                                          showLastComputationRefresh: false,
                                          showFilters: false,
                                      }
                                    : query
                            }
                            setQuery={setSceneQuery}
                            context={{
                                insightProps,
                                showOpenEditorButton: false,
                                hideAIAnalysis: true,
                                hideChartFrame: true,
                                onDateRangeZoom: zoomDateRange,
                            }}
                            filtersOverride={filtersOverride}
                            variablesOverride={variablesOverride}
                        />
                    </CardContent>
                </Card>
                <ChartTypeAccordion insightProps={insightProps} />
            </SceneContent>
        </BindLogic>
    )
}
