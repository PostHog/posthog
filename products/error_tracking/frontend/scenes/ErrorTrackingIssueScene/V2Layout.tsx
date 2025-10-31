import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef } from 'react'

import { IconChevronRight, IconFilter, IconList, IconSearch, IconShare } from '@posthog/icons'
import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { SceneTextInput } from 'lib/components/Scenes/SceneTextInput'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment, IconRobot } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneName, SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'
import { IssueStatusSelect } from './ScenePanel/IssueStatusSelect'
import { ErrorTrackingIssueSceneCategory, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

const EXCEPTION_TABS = {
    exceptions: { icon: <IconList />, label: 'Exceptions' },
    breakdowns: { icon: <IconFilter />, label: 'Breakdowns' },
    autofix: { icon: <IconRobot />, label: 'AI autofix' },
    similar_issues: { icon: <IconSearch />, label: 'Similar issues' },
}

function exceptionTabLabel(category: ErrorTrackingIssueSceneCategory): string {
    const { icon, label } = EXCEPTION_TABS[category]

    return (
        <>
            {icon}
            {label}
        </>
    )
}

export function V2Layout(): JSX.Element {
    const { issue, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')

    const isPostHogSDKIssue = selectedEvent?.properties.$exception_values?.some((v: string) =>
        v.includes('persistence.isDisabled is not a function')
    )

    return (
        <ErrorTrackingSetupPrompt>
            {isPostHogSDKIssue && (
                <LemonBanner
                    type="error"
                    action={{ to: 'https://status.posthog.com/incidents/l70cgmt7475m', children: 'Read more' }}
                    className="mb-4"
                >
                    This issue was captured because of a bug in the PostHog SDK. We've fixed the issue, and you won't be
                    charged for any of these exception events. We recommend setting this issue's status to "Suppressed".
                </LemonBanner>
            )}

            <SceneTitleSection
                resourceType={{ type: 'issue' }}
                name={null}
                description={null}
                actions={
                    <>
                        <ButtonPrimitive
                            onClick={() => {
                                if (!hasDiscussions) {
                                    posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                                }
                                openSidePanel(SidePanelTab.Discussion)
                            }}
                            tooltip="Comment"
                        >
                            <IconComment />
                        </ButtonPrimitive>

                        <ButtonPrimitive
                            onClick={() => {
                                if (issue) {
                                    void copyToClipboard(
                                        window.location.origin + urls.errorTrackingIssue(issue.id),
                                        'issue link'
                                    )
                                }
                            }}
                            tooltip="Share"
                        >
                            <IconShare />
                        </ButtonPrimitive>
                    </>
                }
            />

            {issue && (
                <div className="flex justify-between w-full gap-2">
                    <SceneName name={issue.name ?? undefined} onChange={updateName} canEdit={true} />
                    <div className="flex gap-x-1 items-end">
                        <div>
                            <IssueStatusSelect status={issue.status} onChange={updateStatus} />
                        </div>
                        <div>
                            <IssueAssigneeSelect
                                assignee={issue.assignee}
                                onChange={updateAssignee}
                                disabled={issue.status != 'active'}
                            />
                        </div>
                    </div>
                </div>
            )}

            <LemonDivider className="mt-2" />

            <div className="ErrorTrackingIssue flex">
                <LeftHandColumn />
                <RightHandColumn />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const RightHandColumn = (): JSX.Element => {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    return (
        <div className="flex flex-1 flex-col gap-y-1 pt-4 pl-4">
            <ExceptionCard
                issue={issue ?? undefined}
                issueLoading={issueLoading}
                event={selectedEvent ?? undefined}
                eventLoading={initialEventLoading}
                label={tagRenderer(selectedEvent)}
            />
        </div>
    )
}

const CLOSE_THRESHOLD = 426

const LeftHandColumn = (): JSX.Element => {
    const ref = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        closeThreshold: CLOSE_THRESHOLD,
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const { eventsQuery, eventsQueryKey } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent, setExceptionsCategory } = useActions(errorTrackingIssueSceneLogic)

    return (
        <div
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: desiredSize ?? '30%', minWidth: CLOSE_THRESHOLD }}
            className="flex flex-col relative"
        >
            <TabsPrimitive defaultValue="exceptions" className="flex flex-col gap-y-2">
                <TabsPrimitiveList className="border-b">
                    <TabsPrimitiveTrigger className="px-2 py-1.5" value="exceptions">
                        Exceptions
                    </TabsPrimitiveTrigger>
                    <TabsPrimitiveTrigger className="px-2 py-1.5" value="breakdowns">
                        Breakdowns
                    </TabsPrimitiveTrigger>
                    <TabsPrimitiveTrigger className="px-2 py-1.5" value="autofix">
                        Autofix
                    </TabsPrimitiveTrigger>
                    <TabsPrimitiveTrigger className="px-2 py-1.5" value="similar_issues">
                        Similar issues
                    </TabsPrimitiveTrigger>
                </TabsPrimitiveList>
                <TabsPrimitiveContent value="exceptions">
                    <div className="flex flex-col gap-y-2 pr-2">
                        <ErrorFilters.Root>
                            <div className="flex gap-2 justify-between">
                                <ErrorFilters.DateRange />
                                <ErrorFilters.InternalAccounts />
                            </div>
                            <ErrorFilters.FilterGroup />
                        </ErrorFilters.Root>
                        <Metadata className="">
                            <EventsTable
                                query={eventsQuery}
                                queryKey={eventsQueryKey}
                                selectedEvent={null}
                                onEventSelect={(selectedEvent) => {
                                    if (selectedEvent) {
                                        selectEvent(selectedEvent)
                                        setExceptionsCategory('exception')
                                    }
                                }}
                            />
                        </Metadata>
                    </div>
                </TabsPrimitiveContent>
                <TabsPrimitiveContent value="breakdowns">
                    <BreakdownsSearchBar />
                    <BreakdownsChart />
                </TabsPrimitiveContent>
                <TabsPrimitiveContent value="autofix">AI autofix</TabsPrimitiveContent>
                <TabsPrimitiveContent value="similar_issues">Similar issues</TabsPrimitiveContent>
            </TabsPrimitive>

            <Resizer {...resizerLogicProps} />
        </div>
    )
}
