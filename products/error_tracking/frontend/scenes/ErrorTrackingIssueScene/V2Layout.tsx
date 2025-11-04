import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'

import { IconShare } from '@posthog/icons'
import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { IconComment } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SidePanelTab } from '~/types'

import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export function V2Layout(): JSX.Element {
    const { issue, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    const { openSidePanel } = useActions(sidePanelLogic)

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

            <div className="ErrorTrackingIssue grid grid-cols-10 gap-6">
                <div className="col-span-3 border-r flex flex-col min-h-0">
                    <div className="flex justify-between p-1">
                        <SceneBreadcrumbBackButton />
                        <div>
                            <ButtonPrimitive onClick={() => openSidePanel(SidePanelTab.Discussion)} tooltip="Comment">
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
                        </div>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="p-2 space-y-2">
                        <ErrorTrackingIssueScenePanel showActions={false} />
                    </div>
                </div>
                <div className="flex col-span-7 gap-y-2 flex-col">
                    <Breadcrumbs />
                    <CategoryContent />
                </div>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const CategoryContent = (): JSX.Element => {
    const {
        category,
        exceptionsCategory,
        issue,
        issueLoading,
        selectedEvent,
        initialEventLoading,
        eventsQuery,
        eventsQueryKey,
    } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent, setExceptionsCategory } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    return category === 'breakdowns' ? (
        <div className="flex flex-col gap-2">
            <BreakdownsSearchBar />
            <BreakdownsChart />
        </div>
    ) : exceptionsCategory === 'exception' ? (
        <ExceptionCard
            issue={issue ?? undefined}
            issueLoading={issueLoading}
            event={selectedEvent ?? undefined}
            eventLoading={initialEventLoading}
            label={tagRenderer(selectedEvent)}
        />
    ) : (
        <>
            <ErrorFilters.Root>
                <div className="flex gap-2 justify-between">
                    <ErrorFilters.DateRange />
                    <ErrorFilters.InternalAccounts />
                </div>
                <ErrorFilters.FilterGroup />
            </ErrorFilters.Root>
            <Metadata>
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
        </>
    )
}

const Breadcrumbs = (): JSX.Element => {
    const { category, exceptionsCategory } = useValues(errorTrackingIssueSceneLogic)
    const { setCategory, setExceptionsCategory } = useActions(errorTrackingIssueSceneLogic)

    return (
        <div className="flex items-center gap-x-2 border bg-surface-tertiary py-1 px-2 rounded">
            <div>Issue</div>
            <div>/</div>
            <div className="flex items-center">
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive size="xs">
                            <span className="capitalize">{category}</span>
                            <DropdownMenuOpenIndicator />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent loop align="start" side="bottom">
                        <DropdownMenuGroup>
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger asChild>
                                    <ButtonPrimitive menuItem>
                                        Exceptions
                                        <DropdownMenuOpenIndicator intent="sub" />
                                    </ButtonPrimitive>
                                </DropdownMenuSubTrigger>
                                <DropdownMenuSubContent>
                                    <DropdownMenuItem asChild>
                                        <ButtonPrimitive
                                            menuItem
                                            onClick={() => {
                                                setCategory('exceptions')
                                                setExceptionsCategory('exception')
                                            }}
                                        >
                                            Last seen
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem asChild>
                                        <ButtonPrimitive
                                            menuItem
                                            onClick={() => {
                                                setCategory('exceptions')
                                                setExceptionsCategory('all')
                                            }}
                                        >
                                            All
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={() => setCategory('breakdowns')}>
                                    Breakdowns
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
            {category === 'exceptions' && exceptionsCategory != 'all' ? (
                <>
                    <div>/</div>
                    <div>Exception</div>
                </>
            ) : null}
        </div>
    )
}
