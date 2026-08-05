import '../ErrorTrackingIssueScene/ErrorTrackingIssueScene.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconFilter, IconList, IconRefresh, IconRewindPlay, IconX } from '@posthog/icons'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { Button, Tabs, TabsContent, TabsList, TabsTrigger, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, ReplayTabs } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { PostHogSDKIssueBanner } from '../../components/Banners/PostHogSDKIssueBanner'
import { breakdownFiltersLogic } from '../../components/Breakdowns/breakdownFiltersLogic'
import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { MiniBreakdowns } from '../../components/Breakdowns/MiniBreakdowns'
import { miniBreakdownsLogic } from '../../components/Breakdowns/miniBreakdownsLogic'
import { eventsSourceLogic } from '../../components/EventsTable/eventsSourceLogic'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { StackTraceActions } from '../../components/ExceptionCard/Tabs/StackTraceTab/StackTraceActions'
import { StatusIndicator } from '../../components/Indicators'
import { ErrorFilters } from '../../components/IssueFilters'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { Metadata } from '../../components/IssueMetadata'
import { IssueStatusButton } from '../../components/IssueStatusButton'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { getIssueReplayDateRange } from '../../utils'
import {
    ErrorTrackingIssueSceneCategory,
    errorTrackingIssueSceneConfigurationLogic,
} from './errorTrackingIssueSceneConfigurationLogic'
import {
    ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY,
    ErrorTrackingIssueSceneLogicProps,
    errorTrackingIssueSceneLogic,
} from './errorTrackingIssueSceneLogic'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueId, lastSeen, mobileDetailOpen } = useValues(errorTrackingIssueSceneLogic)
    const { updateAssignee, updateStatus, updateName, setMobileDetailOpen } = useActions(errorTrackingIssueSceneLogic)
    const { isWindowLessThan } = useWindowSize()
    const isMobile = isWindowLessThan('md')
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')

    // breakdownFiltersLogic is a keyless singleton that miniBreakdownsLogic connects to. Mounting it here ties its
    // lifecycle to the scene (the stable parent), so it is torn down after the keyed miniBreakdownsLogic below rather
    // than mid-cascade — otherwise its store path can vanish while miniBreakdownsLogic's connected selectors still
    // re-evaluate, throwing "Can not find path breakdownFiltersLogic".
    useMountedLogic(breakdownFiltersLogic)

    useAttachedContext(
        issueId ? [{ type: 'error_tracking_issue', key: issueId, label: issue?.name ?? undefined }] : null
    )

    useEffect(() => {
        const utmSource = new URLSearchParams(window.location.search).get('utm_source')
        posthog.capture('error_tracking_issue_viewed', {
            issue_id: issueId,
            ...(utmSource ? { utm_source: utmSource } : {}),
        })
    }, [issueId])

    return (
        <ErrorTrackingSetupPrompt>
            <div data-quill className="ErrorTrackingIssueScene">
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }}>
                    <BindLogic logic={miniBreakdownsLogic} props={{ issueId }}>
                        {issue && (
                            <div className="flex flex-col h-[calc(var(--scene-layout-rect-height))]">
                                <div data-not-quill className="contents">
                                    {sceneMenuBarEnabled && (
                                        <SceneMenuBar>
                                            <SceneMenuBarMenu label="File" dataAttr="issue-menubar-file">
                                                <SceneMenuBarFileItems dataAttrKey="issue" />
                                                {hasIssueSplitting && (
                                                    <SceneMenuBarItem
                                                        onClick={() =>
                                                            window.open(
                                                                urls.errorTrackingIssueFingerprints(issue.id),
                                                                '_self'
                                                            )
                                                        }
                                                        data-attr="issue-menubar-fingerprints"
                                                    >
                                                        Manage fingerprints
                                                    </SceneMenuBarItem>
                                                )}
                                            </SceneMenuBarMenu>
                                            <SceneMenuBarMenu label="View" dataAttr="issue-menubar-view">
                                                <SceneMenuBarItem
                                                    onClick={() => {
                                                        const url = urls.replay(ReplayTabs.Home, {
                                                            ...getIssueReplayDateRange(issue.first_seen, lastSeen),
                                                            filter_group: {
                                                                type: FilterLogicalOperator.And,
                                                                values: [
                                                                    {
                                                                        type: FilterLogicalOperator.And,
                                                                        values: [
                                                                            {
                                                                                key: '$exception_issue_id',
                                                                                type: PropertyFilterType.Event,
                                                                                operator: PropertyOperator.Exact,
                                                                                value: [issue.id],
                                                                            },
                                                                        ],
                                                                    },
                                                                ],
                                                            },
                                                        })
                                                        newInternalTab(url)
                                                    }}
                                                    data-attr="issue-menubar-view-recordings"
                                                >
                                                    <IconRewindPlay />
                                                    View recordings
                                                </SceneMenuBarItem>
                                            </SceneMenuBarMenu>
                                        </SceneMenuBar>
                                    )}
                                    <SceneTitleSection
                                        canEdit
                                        name={issue.name ?? undefined}
                                        onNameChange={updateName}
                                        description={null}
                                        resourceType={{ type: 'error_tracking' }}
                                        className={clsx(
                                            'pl-4 pr-2 h-[50px] @2xl/main-content:relative top-[0px] mt-0 mx-0 mb-0',
                                            isMobile
                                                ? '[&>.scene-title-section]:flex-row [&>.scene-title-section]:items-center [&>.scene-title-section>*:last-child]:order-last'
                                                : undefined
                                        )}
                                        actions={
                                            isMobile ? undefined : (
                                                <div className="flex items-center gap-1">
                                                    <div className="flex h-7 items-center">
                                                        <div className="flex h-7 items-center">
                                                            <StatusIndicator status={issue.status} withTooltip />
                                                        </div>
                                                    </div>
                                                    <IssueAssigneeSelect
                                                        assignee={issue.assignee}
                                                        onChange={updateAssignee}
                                                    />
                                                    <Button
                                                        variant="outline"
                                                        size="default"
                                                        data-attr="error-tracking-issue-view-recordings"
                                                        onClick={() => {
                                                            newInternalTab(
                                                                urls.replay(ReplayTabs.Home, {
                                                                    ...getIssueReplayDateRange(
                                                                        issue.first_seen,
                                                                        lastSeen
                                                                    ),
                                                                    filter_group: {
                                                                        type: FilterLogicalOperator.And,
                                                                        values: [
                                                                            {
                                                                                type: FilterLogicalOperator.And,
                                                                                values: [
                                                                                    {
                                                                                        key: '$exception_issue_id',
                                                                                        type: PropertyFilterType.Event,
                                                                                        operator:
                                                                                            PropertyOperator.Exact,
                                                                                        value: [issue.id],
                                                                                    },
                                                                                ],
                                                                            },
                                                                        ],
                                                                    },
                                                                })
                                                            )
                                                        }}
                                                    >
                                                        View recordings
                                                        <IconRewindPlay />
                                                    </Button>
                                                    <IssueStatusButton status={issue.status} onChange={updateStatus} />
                                                </div>
                                            )
                                        }
                                    />

                                    {isMobile && (
                                        <div className="flex items-center gap-1.5 px-2 py-1.5 border-b flex-wrap">
                                            <div className="flex h-7 items-center">
                                                <StatusIndicator status={issue.status} withTooltip />
                                            </div>
                                            <IssueAssigneeSelect assignee={issue.assignee} onChange={updateAssignee} />
                                            <IssueStatusButton status={issue.status} onChange={updateStatus} />
                                            {!mobileDetailOpen && (
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() => setMobileDetailOpen(true)}
                                                >
                                                    Details
                                                </Button>
                                            )}
                                        </div>
                                    )}

                                    <ErrorTrackingIssueScenePanel issue={issue} />
                                </div>

                                <div className="ErrorTrackingIssue flex flex-grow min-h-0 overflow-hidden">
                                    <div className="relative flex flex-1 h-full w-full min-h-0">
                                        <LeftHandColumn isMobile={isMobile} />
                                        <RightHandColumn
                                            isMobile={isMobile}
                                            isOpen={mobileDetailOpen}
                                            onClose={() => setMobileDetailOpen(false)}
                                        />
                                    </div>
                                </div>
                            </div>
                        )}
                    </BindLogic>
                </BindLogic>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const RightHandColumn = ({
    isMobile,
    isOpen,
    onClose,
}: {
    isMobile: boolean
    isOpen: boolean
    onClose: () => void
}): JSX.Element | null => {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    if (isMobile && !isOpen) {
        return null
    }

    return (
        <div
            className={clsx(
                'flex min-h-0 flex-1 flex-col gap-1 bg-[var(--background)]',
                isMobile ? 'absolute inset-0 z-20' : 'min-w-[375px]'
            )}
        >
            {isMobile && (
                <div className="flex items-center justify-between p-1 shrink-0">
                    <div data-not-quill className="flex items-center gap-1 pl-1">
                        {selectedEvent?.timestamp && (
                            <TZLabel className="text-xs text-muted-foreground" time={selectedEvent.timestamp} />
                        )}
                        {tagRenderer(selectedEvent)}
                    </div>
                    <Button variant="outline" size="icon-sm" onClick={onClose} aria-label="Close detail">
                        <IconX />
                    </Button>
                </div>
            )}
            <div data-not-quill className="contents">
                <PostHogSDKIssueBanner event={selectedEvent} />
            </div>
            <div className="flex-1 min-h-0 flex flex-col">
                <ExceptionCard
                    issueId={issue?.id ?? 'no-issue'}
                    issueName={issue?.name ?? null}
                    loading={issueLoading || initialEventLoading}
                    event={selectedEvent ?? undefined}
                    label={
                        <span data-not-quill className="contents">
                            {tagRenderer(selectedEvent)}
                        </span>
                    }
                    hideEventMeta={isMobile}
                    renderStackTraceActions={() => {
                        return issue ? <StackTraceActions issue={issue} /> : null
                    }}
                />
            </div>
        </div>
    )
}

const LeftHandColumn = ({ isMobile }: { isMobile: boolean }): JSX.Element => {
    const { category } = useValues(errorTrackingIssueSceneConfigurationLogic)
    const { setCategory } = useActions(errorTrackingIssueSceneConfigurationLogic)
    const { issueId } = useValues(errorTrackingIssueSceneLogic)

    const ref = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        placement: 'right',
        persistPrefix: 'error-tracking-issue-view-columns-ratio',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                isMobile
                    ? undefined
                    : {
                          width: desiredSize ?? '40%',
                          minWidth: 320,
                      }
            }
            className={clsx('relative flex h-full flex-col bg-[var(--background)]', isMobile && 'max-w-full flex-1')}
        >
            <Tabs
                value={category}
                onValueChange={(value) => {
                    setCategory(value as ErrorTrackingIssueSceneCategory)
                    posthog.capture('error_tracking_issue_tab_viewed', { issue_id: issueId, tab: value })
                }}
                className="min-h-0 flex-1 gap-0"
            >
                <div>
                    <ScrollableShadows direction="horizontal" className="border-b border-border" hideScrollbars>
                        <TabsList variant="line" className="flex space-x-0.5 gap-2">
                            <TabsTrigger className="flex flex-none items-center px-2 py-1.5" value="exceptions">
                                <IconList className="mr-1" />
                                <span className="text-nowrap">Exceptions</span>
                            </TabsTrigger>
                            <TabsTrigger className="flex flex-none items-center px-2 py-1.5" value="breakdowns">
                                <IconFilter className="mr-1" />
                                <span className="text-nowrap">Breakdowns</span>
                            </TabsTrigger>
                        </TabsList>
                    </ScrollableShadows>
                </div>
                <TabsContent value="exceptions" className="h-full min-h-0">
                    <ExceptionsTab />
                </TabsContent>
                <TabsContent value="breakdowns" className="flex-1 min-h-0">
                    <BreakdownsTab />
                </TabsContent>
            </Tabs>

            {!isMobile && <Resizer {...resizerLogicProps} />}
        </div>
    )
}

const ExceptionsTab = (): JSX.Element => {
    const { eventsQuery, eventsQueryKey, selectedEvent, issueFingerprints, issueFingerprintsLoading } =
        useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const eventsDataSource = eventsSourceLogic({ query: eventsQuery, queryKey: eventsQueryKey })
    const { itemsLoading, canLoadNextData } = useValues(eventsDataSource)
    const { loadData, loadNextData } = useActions(eventsDataSource)

    return (
        <div className="flex flex-col h-full min-h-0">
            <Metadata
                className="flex flex-col flex-1 min-h-0"
                onScrollNearEnd={() => {
                    if (canLoadNextData && !itemsLoading) {
                        loadNextData()
                    }
                }}
            >
                <div className="sticky top-0 z-10 shrink-0 border-y border-border bg-[var(--background)] px-2 py-2">
                    <ErrorFilters.Root className="w-full">
                        <div className="flex w-full flex-col gap-1">
                            <div className="flex w-full flex-wrap items-center gap-1">
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="outline"
                                                size="icon"
                                                loading={itemsLoading}
                                                aria-label="Reload exceptions"
                                                onClick={() => loadData()}
                                            />
                                        }
                                    >
                                        <IconRefresh />
                                    </TooltipTrigger>
                                    <TooltipContent>Reload exceptions</TooltipContent>
                                </Tooltip>
                                <ErrorFilters.DateRange />
                                <div className="ml-auto shrink-0">
                                    <ErrorFilters.InternalAccounts />
                                </div>
                            </div>
                            <div className="flex w-full flex-wrap items-center gap-1">
                                <ErrorFilters.Search
                                    className="w-auto min-w-40 flex-1 shrink"
                                    placeholder="Search exceptions"
                                />
                                <ErrorFilters.FilterGroup />
                            </div>
                        </div>
                    </ErrorFilters.Root>
                </div>
                {issueFingerprintsLoading ? (
                    <div className="px-2 py-3 text-sm text-muted-foreground">Loading exceptions...</div>
                ) : issueFingerprints.length === 0 ? (
                    <div className="px-2 py-3 text-sm text-muted-foreground">No exceptions found for this issue.</div>
                ) : (
                    <EventsTable
                        query={eventsQuery}
                        queryKey={eventsQueryKey}
                        selectedEvent={selectedEvent}
                        onEventSelect={(selectedEvent) => {
                            if (selectedEvent) {
                                selectEvent(selectedEvent)
                            }
                        }}
                    />
                )}
            </Metadata>
        </div>
    )
}
const BreakdownsTab = (): JSX.Element => {
    return (
        <div className="flex flex-col h-full">
            <BreakdownsSearchBar />
            <MiniBreakdowns />
            <BreakdownsChart />
        </div>
    )
}
