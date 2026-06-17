import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBadge, LemonBanner, LemonButton, LemonTab, LemonTabs, Link, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { CyclotronJobFiltersType } from '~/types'

import { IntegrationsMovedBanner } from '../../components/IntegrationsMovedBanner'
import { ErrorTrackingIssueFilteringTool } from '../../components/IssueFilteringTool'
import { FilterBar } from '../../components/IssueFilters/FilterBar'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import {
    SearchBarVariantToggle,
    useErrorTrackingSearchBarRedesign,
} from '../../components/IssueFilters/SearchBarVariantToggle'
import { IssueReloadButton } from '../../components/IssueQueryOptions/IssueQueryOptions'
import { issueQueryOptionsLogic } from '../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { exceptionIngestionLogic } from '../../components/SetupPrompt/exceptionIngestionLogic'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { StyleVariables } from '../../components/StyleVariables'
import { issuesDataNodeLogic } from '../../logics/issuesDataNodeLogic'
import { ERROR_TRACKING_LOGIC_KEY } from '../../utils'
import {
    ERROR_TRACKING_SCENE_LOGIC_KEY,
    ErrorTrackingSceneActiveTab,
    errorTrackingSceneLogic,
} from './errorTrackingSceneLogic'
import { ErrorTrackingInsights } from './tabs/insights/ErrorTrackingInsights'
import { IssuesFilters } from './tabs/issues/IssuesFilters'
import { IssuesList, insightProps } from './tabs/issues/IssuesList'
import { SourceMapsBanner } from './tabs/issues/SourceMapsBanner'
import { RecommendationsTab } from './tabs/recommendations/RecommendationsTab'
import { recommendationsTabLogic } from './tabs/recommendations/recommendationsTabLogic'

const ERROR_TRACKING_ALERT_FILTER_GROUPS: CyclotronJobFiltersType[] = [
    { events: [{ id: '$error_tracking_issue_created', type: 'events' }] },
    { events: [{ id: '$error_tracking_issue_reopened', type: 'events' }] },
    { events: [{ id: '$error_tracking_issue_spiking', type: 'events' }] },
]

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

const IssuesTab = (): JSX.Element => {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(exceptionIngestionLogic)
    const { query } = useValues(errorTrackingSceneLogic)
    const hasSourceMapsBanner = useFeatureFlag('ERROR_TRACKING_SOURCE_MAPS_BANNER')
    const newSearchBar = useErrorTrackingSearchBarRedesign()

    const banners = (
        <>
            <ErrorTrackingIssueFilteringTool />
            {hasSentExceptionEventLoading || hasSentExceptionEvent ? null : <IngestionStatusCheck />}
            {hasSourceMapsBanner ? <SourceMapsBanner /> : null}
        </>
    )

    if (!newSearchBar) {
        return (
            <ErrorTrackingSetupPrompt>
                {banners}
                <div className="relative border rounded bg-surface-primary p-2">
                    <SearchBarVariantToggle />
                    <IssuesFilters />
                </div>
                <IssuesList />
            </ErrorTrackingSetupPrompt>
        )
    }

    return (
        <ErrorTrackingSetupPrompt>
            <BindLogic
                logic={issuesDataNodeLogic}
                props={{ key: insightVizDataNodeKey(insightProps), query: query.source }}
            >
                {banners}
                {/* The sceneInset tab content already pads 16px all around. Keep py-2 so the
                    stuck bar has background buffer, and offset it with margins so the resting
                    gaps stay at 16px (top: 16 - 8 + 8, bottom: 8 + 8). */}
                <SceneStickyBar showBorderBottom={false} className="py-2 -mt-2 mb-2">
                    <div className="relative">
                        <SearchBarVariantToggle />
                        <FilterBar
                            reload={<IssueReloadButton />}
                            logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                            quickFilterContext={QuickFilterContext.ErrorTrackingIssueFilters}
                        />
                    </div>
                </SceneStickyBar>
                <IssuesList />
            </BindLogic>
        </ErrorTrackingSetupPrompt>
    )
}

export function ErrorTrackingScene(): JSX.Element {
    const { activeTab } = useValues(errorTrackingSceneLogic)
    const { setActiveTab } = useActions(errorTrackingSceneLogic)
    const hasRecommendations = useFeatureFlag('ERROR_TRACKING_RECOMMENDATIONS')

    useOnMountEffect(() => {
        const utmSource = new URLSearchParams(window.location.search).get('utm_source')
        api.hogFunctions
            .list({
                types: ['internal_destination'],
                filter_groups: ERROR_TRACKING_ALERT_FILTER_GROUPS,
            })
            .then((res) => {
                posthog.capture('error_tracking_issues_list_viewed', {
                    active_tab: activeTab,
                    alert_destination_count: res.results.length,
                    ...(utmSource ? { utm_source: utmSource } : {}),
                })
            })
    })

    const tabs: LemonTab<ErrorTrackingSceneActiveTab>[] = [
        {
            key: 'issues',
            label: 'Issues',
            content: <IssuesTab />,
        },
        {
            key: 'insights',
            label: 'Insights',
            content: <ErrorTrackingInsights />,
        },
        ...(hasRecommendations
            ? [
                  {
                      key: 'recommendations' as const,
                      label: <RecommendationsTabLabel />,
                      content: <RecommendationsTab />,
                  },
              ]
            : []),
        {
            key: 'configuration',
            label: 'Configuration',
            content: (
                <>
                    <IntegrationsMovedBanner />
                    <Settings
                        logicKey={ERROR_TRACKING_LOGIC_KEY}
                        sectionId="environment-error-tracking-configuration"
                        settingId="error-tracking-alerting"
                        handleLocally
                    />
                </>
            ),
        },
    ]

    return (
        <StyleVariables>
            <BindLogic logic={issueFiltersLogic} props={{ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }}>
                <BindLogic logic={issueQueryOptionsLogic} props={{ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY }}>
                    <SceneContent>
                        <Header />
                        <LemonTabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} tabs={tabs} sceneInset />
                    </SceneContent>
                </BindLogic>
            </BindLogic>
        </StyleVariables>
    )
}

const RecommendationsTabLabel = (): JSX.Element => {
    const { activeRecommendations, recommendationsLoading } = useValues(recommendationsTabLogic)

    return (
        <span className="flex items-center gap-1.5">
            Recommendations
            {recommendationsLoading ? (
                <LemonBadge size="small" content={<Spinner textColored />} />
            ) : (
                <LemonBadge.Number count={activeRecommendations.length} size="small" showZero />
            )}
        </span>
    )
}

const Header = (): JSX.Element => {
    const { isDev } = useValues(preflightLogic)

    const buildExceptionSteps = (): {
        $type: string
        $message: string
        $level: string
        $timestamp: string
    }[] => {
        const now = new Date()
        return [
            {
                $type: 'ui.interaction',
                $message: 'Send an exception button clicked',
                $level: 'info',
                $timestamp: new Date(now.getTime() - 2500).toISOString(),
            },
            {
                $type: 'http',
                $message: 'GET /api/environments/:team_id/error_tracking/issues/',
                $level: 'info',
                $timestamp: new Date(now.getTime() - 1200).toISOString(),
            },
            {
                $type: 'error',
                $message: 'Kaboom thrown from issues list',
                $level: 'error',
                $timestamp: now.toISOString(),
            },
        ]
    }

    const onClick = (): void => {
        setInterval(() => {
            throw new Error('Kaboom !')
        }, 100)
    }

    return (
        <>
            <SceneTitleSection
                name={sceneConfigurations[Scene.ErrorTracking].name}
                description={null}
                resourceType={{
                    type: sceneConfigurations[Scene.ErrorTracking].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        {isDev ? (
                            <>
                                <LemonButton
                                    size="small"
                                    onClick={() => {
                                        posthog.captureException(new Error('Kaboom !'), {
                                            $exception_steps: buildExceptionSteps(),
                                        })
                                    }}
                                >
                                    Send an exception
                                </LemonButton>
                                <LemonButton size="small" onClick={onClick}>
                                    Start exception loop
                                </LemonButton>
                            </>
                        ) : null}
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconFeedback />}
                            onClick={() => posthog.displaySurvey('019cbd35-c91c-0000-9997-9259dc4cc2ef')}
                        >
                            Feedback
                        </LemonButton>
                        <LemonButton
                            size="small"
                            to="https://posthog.com/docs/error-tracking"
                            type="secondary"
                            targetBlank
                        >
                            Documentation
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    return (
        <LemonBanner type="warning" className="my-2">
            <p>
                <strong>No Exception events have been detected!</strong>
            </p>
            <p>
                To use the Error tracking product, please{' '}
                <Link to="https://posthog.com/docs/error-tracking/installation">
                    enable exception capture within the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
        </LemonBanner>
    )
}
