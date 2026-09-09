import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBadge, LemonButton, LemonTab, LemonTabs, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { AccessDenied } from 'lib/components/AccessDenied'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { IconFeedback } from 'lib/lemon-ui/icons'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, CyclotronJobFiltersType } from '~/types'

import { IntegrationsMovedBanner } from '../../components/IntegrationsMovedBanner'
import { ErrorTrackingIssueFilteringTool } from '../../components/IssueFilteringTool'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { issueQueryOptionsLogic } from '../../components/IssueQueryOptions/issueQueryOptionsLogic'
import { StyleVariables } from '../../components/StyleVariables'
import { errorTrackingEmptyState } from '../../emptyState/errorTrackingEmptyState'
import { ERROR_TRACKING_LOGIC_KEY } from '../../utils'
import {
    ERROR_TRACKING_SCENE_LOGIC_KEY,
    ErrorTrackingSceneActiveTab,
    errorTrackingSceneLogic,
} from './errorTrackingSceneLogic'
import { ErrorTrackingInsights } from './tabs/insights/ErrorTrackingInsights'
import { IssuesList } from './tabs/issues/IssuesList'
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
    productKey: ProductKey.ERROR_TRACKING,
    emptyState: errorTrackingEmptyState,
}

export function ErrorTrackingScene(): JSX.Element {
    const { activeTab } = useValues(errorTrackingSceneLogic)
    const { setActiveTab } = useActions(errorTrackingSceneLogic)
    const hasRecommendations = useFeatureFlag('ERROR_TRACKING_RECOMMENDATIONS')
    // Same gate as the settings section: configuration endpoints require error tracking viewer access.
    const configurationAccessDeniedReason = getAccessControlDisabledReason(
        AccessControlResourceType.ErrorTracking,
        AccessControlLevel.Viewer
    )

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
            content: (
                <>
                    <SourceMapsBanner />
                    <IssuesList />
                    {/* Renders a hidden div — keep it after IssuesList so the sticky bar's
                        first:-mt-4 can detect whether a banner renders above it */}
                    <ErrorTrackingIssueFilteringTool />
                </>
            ),
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
            disabledReason: configurationAccessDeniedReason ?? undefined,
            content: configurationAccessDeniedReason ? (
                // Deep links can activate the tab even though it's disabled, so the
                // content must deny too — not just the tab button.
                <AccessDenied reason={configurationAccessDeniedReason} />
            ) : (
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
