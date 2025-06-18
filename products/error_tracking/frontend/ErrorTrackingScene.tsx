import { IconChevronDown, IconChevronRight, IconGear, IconMinus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonDivider, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { posthog } from 'posthog-js'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from './components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from './components/Assignee/AssigneeSelect'
import { ErrorFilters } from './components/ErrorFilters'
import { errorIngestionLogic } from './components/ErrorTrackingSetupPrompt/errorIngestionLogic'
import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import { IssueStatusSelect } from './components/IssueStatusSelect'
import { RuntimeIcon } from './components/RuntimeIcon'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { ErrorTrackingListOptions } from './ErrorTrackingListOptions'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { useSparklineData } from './hooks/use-sparkline-data'
import { OccurrenceSparkline } from './OccurrenceSparkline'
import { ERROR_TRACKING_LISTING_RESOLUTION } from './utils'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(errorIngestionLogic)
    const { query } = useValues(errorTrackingSceneLogic)
    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingQuery',
    }

    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: CustomGroupTitleColumn,
                renderTitle: CustomGroupTitleHeader,
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

    return (
        <ErrorTrackingSetupPrompt>
            <BindLogic logic={errorTrackingDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
                <Header />
                {hasSentExceptionEventLoading || hasSentExceptionEvent ? null : <IngestionStatusCheck />}
                <ErrorFilters.Root>
                    <ErrorFilters.DateRange />
                    <ErrorFilters.FilterGroup />
                    <ErrorFilters.InternalAccounts />
                </ErrorFilters.Root>
                <LemonDivider className="mt-2" />
                <ErrorTrackingListOptions />
                <Query query={query} context={context} />
            </BindLogic>
        </ErrorTrackingSetupPrompt>
    )
}

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const { dateRange } = useValues(errorTrackingSceneLogic)
    const record = props.record as ErrorTrackingIssue
    if (!record.aggregations) {
        throw new Error('No aggregations found')
    }
    const data = useSparklineData(record.aggregations.volumeRange, dateRange, ERROR_TRACKING_LISTING_RESOLUTION)
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

const CustomGroupTitleHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { results } = useValues(errorTrackingDataNodeLogic)
    const allSelected = results.length == selectedIssueIds.length && selectedIssueIds.length > 0

    return (
        <div className="flex gap-2 items-center">
            <LemonCheckbox
                checked={allSelected}
                onChange={() => (allSelected ? setSelectedIssueIds([]) : setSelectedIssueIds(results.map((r) => r.id)))}
            />
            {columnName}
        </div>
    )
}

const CustomGroupSeparator = (): JSX.Element => <IconMinus className="text-quaternary" transform="rotate(90)" />

const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { updateIssueAssignee, updateIssueStatus } = useActions(issueActionsLogic)
    const record = props.record as ErrorTrackingIssue
    const checked = selectedIssueIds.includes(record.id)
    const runtime = getRuntimeFromLib(record.library)

    return (
        <div className="flex items-start gap-x-2 group my-1">
            <LemonCheckbox
                className="h-[1.2rem]"
                checked={checked}
                onChange={(newValue) => {
                    setSelectedIssueIds(
                        newValue
                            ? [...new Set([...selectedIssueIds, record.id])]
                            : selectedIssueIds.filter((id) => id != record.id)
                    )
                }}
            />

            <div className="flex flex-col gap-[2px]">
                <Link
                    className="flex-1 pr-12"
                    to={urls.errorTrackingIssue(record.id)}
                    onClick={() => {
                        const issueLogic = errorTrackingIssueSceneLogic({ id: record.id })
                        issueLogic.mount()
                        issueLogic.actions.setIssue(record)
                    }}
                >
                    <div className="flex items-center h-[1.2rem] gap-2">
                        <RuntimeIcon runtime={runtime} fontSize="0.8rem" />
                        <span className="font-semibold text-[1.2em]">{record.name || 'Unknown Type'}</span>
                    </div>
                </Link>
                <div className="line-clamp-1 text-secondary">{record.description}</div>
                <div className="flex items-center text-secondary">
                    <IssueStatusSelect
                        status={record.status}
                        onChange={(status) => updateIssueStatus(record.id, status)}
                    />
                    <CustomGroupSeparator />
                    <AssigneeSelect
                        assignee={record.assignee}
                        onChange={(assignee) => updateIssueAssignee(record.id, assignee)}
                    >
                        {(anyAssignee) => (
                            <div
                                className="flex items-center hover:bg-fill-button-tertiary-hover p-[0.1rem] rounded cursor-pointer"
                                role="button"
                            >
                                <AssigneeIconDisplay assignee={anyAssignee} size="xsmall" />
                                <AssigneeLabelDisplay
                                    assignee={anyAssignee}
                                    className="ml-1 text-xs text-secondary"
                                    size="xsmall"
                                />
                                <IconChevronDown />
                            </div>
                        )}
                    </AssigneeSelect>
                    <CustomGroupSeparator />
                    <TZLabel time={record.first_seen} className="border-dotted border-b text-xs ml-1" delayMs={750} />
                    <IconChevronRight className="text-quaternary mx-1" />
                    {record.last_seen ? (
                        <TZLabel time={record.last_seen} className="border-dotted border-b text-xs" delayMs={750} />
                    ) : (
                        <LemonSkeleton />
                    )}
                </div>
            </div>
        </div>
    )
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
    const { user } = useValues(userLogic)

    const onClick = (): void => {
        setInterval(() => {
            throw new Error('Kaboom !')
        }, 100)
    }

    return (
        <PageHeader
            buttons={
                <>
                    {user?.is_staff ? (
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
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    return (
        <LemonBanner type="warning" className="my-4">
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
