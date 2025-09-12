import { BindLogic, useValues } from 'kea'
import { posthog } from 'posthog-js'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, Link, Tooltip } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { ErrorTrackingListOptions } from './ErrorTrackingListOptions'
import { OccurrenceSparkline } from './OccurrenceSparkline'
import { ErrorFilters } from './components/ErrorFilters'
import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { errorIngestionLogic } from './components/ErrorTrackingSetupPrompt/errorIngestionLogic'
import { ErrorTrackingIssueFilteringTool } from './components/IssueFilteringTool'
import { ErrorTrackingIssueImpactTool } from './components/IssueImpactTool'
import { IssueListTitleColumn, IssueListTitleHeader } from './components/TableColumns'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { useSparklineData } from './hooks/use-sparkline-data'
import { ERROR_TRACKING_LISTING_RESOLUTION } from './utils'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(errorIngestionLogic)
    const { query } = useValues(errorTrackingSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingQuery',
    }

    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: TitleColumn,
                renderTitle: TitleHeader,
            },
            occurrences: { align: 'center', render: CountColumn },
            sessions: { align: 'center', render: CountColumn },
            users: { align: 'center', render: CountColumn },
            volume: { align: 'right', renderTitle: VolumeColumnHeader, render: VolumeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }

    // TODO - fix feature flag check once the feature flag is created etc
    return (
        <ErrorTrackingSetupPrompt>
            <ErrorTrackingIssueFilteringTool />
            {featureFlags[FEATURE_FLAGS.ERROR_TRACKING_IMPACT_MAX_TOOL] && <ErrorTrackingIssueImpactTool />}
            <SceneContent className="ErrorTracking">
                <BindLogic logic={errorTrackingDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
                    <Header />
                    {hasSentExceptionEventLoading || hasSentExceptionEvent ? null : <IngestionStatusCheck />}
                    <div>
                        <ErrorFilters.Root>
                            <ErrorFilters.DateRange />
                            <ErrorFilters.FilterGroup />
                            <ErrorFilters.InternalAccounts />
                        </ErrorFilters.Root>
                        <LemonDivider className="mt-2" />
                        <ErrorTrackingListOptions />
                        <Query query={query} context={context} />
                    </div>
                </BindLogic>
            </SceneContent>
        </ErrorTrackingSetupPrompt>
    )
}

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue
    if (!record.aggregations) {
        throw new Error('No aggregations found')
    }
    const data = useSparklineData(record.aggregations, ERROR_TRACKING_LISTING_RESOLUTION)
    return (
        <div className="flex justify-end">
            <OccurrenceSparkline className="h-8" data={data} displayXAxis={false} />
        </div>
    )
}

const VolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    return (
        <div className="flex justify-between items-center min-w-64">
            <div>{columnName}</div>
        </div>
    )
}

const TitleHeader: QueryContextColumnTitleComponent = (): JSX.Element => {
    const { results } = useValues(errorTrackingDataNodeLogic)
    return <IssueListTitleHeader results={results} />
}

const TitleColumn: QueryContextColumnComponent = (props): JSX.Element => {
    const { results } = useValues(errorTrackingDataNodeLogic)

    return <IssueListTitleColumn results={results} {...props} />
}

const CountColumn = ({ record, columnName }: { record: unknown; columnName: string }): JSX.Element => {
    const aggregations = (record as ErrorTrackingIssue).aggregations
    const count = aggregations ? aggregations[columnName as 'occurrences' | 'sessions' | 'users'] : 0

    return (
        <span className="text-lg font-medium">
            {columnName === 'sessions' && count === 0 ? (
                <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
                    -
                </Tooltip>
            ) : (
                humanFriendlyLargeNumber(count)
            )}
        </span>
    )
}

const Header = (): JSX.Element => {
    const { isDev } = useValues(preflightLogic)

    const onClick = (): void => {
        setInterval(() => {
            throw new Error('Kaboom !')
        }, 100)
    }

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        {isDev ? (
                            <>
                                <LemonButton
                                    onClick={() => {
                                        posthog.captureException(new Error('Kaboom !'))
                                    }}
                                >
                                    Send an exception
                                </LemonButton>
                                <LemonButton onClick={onClick}>Start exception loop</LemonButton>
                            </>
                        ) : null}
                        <LemonButton to="https://posthog.com/docs/error-tracking" type="secondary" targetBlank>
                            Documentation
                        </LemonButton>
                        <LemonButton to={urls.errorTrackingConfiguration()} type="secondary" icon={<IconGear />}>
                            Configure
                        </LemonButton>
                    </>
                }
            />
            <SceneTitleSection
                name="Error tracking"
                description="Track and analyze errors in your website or application to understand and fix issues."
                resourceType={{
                    type: 'error_tracking',
                }}
            />
            <SceneDivider />
        </>
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <LemonBanner type="warning" className={cn(!newSceneLayout && 'mb-4')}>
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
