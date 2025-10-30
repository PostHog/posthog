import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronRight, IconFilter, IconList, IconSearch, IconShare } from '@posthog/icons'
import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

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
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanelV2 } from './ScenePanel'
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
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
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
                <div className="col-span-3 flex flex-col min-h-0">
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

                    <LemonDivider className="mb-2" />

                    <ErrorTrackingIssueScenePanelV2 />
                </div>
                <div className="flex col-span-7 gap-y-1 flex-col">
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
    ) : category === 'similar_issues' ? (
        <div>Similar issues coming soon</div>
    ) : category === 'autofix' ? (
        <div>Autofix coming soon</div>
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
    const { isViewingException } = useValues(errorTrackingIssueSceneLogic)
    const { setExceptionsCategory } = useActions(errorTrackingIssueSceneLogic)

    return (
        <div className="flex items-center gap-x-1">
            {isViewingException ? (
                <>
                    <ButtonGroupPrimitive groupVariant="outline">
                        <ButtonPrimitive hasSideActionRight onClick={() => setExceptionsCategory('all')}>
                            {exceptionTabLabel('exceptions')}
                        </ButtonPrimitive>

                        <CategoryDropdown />
                    </ButtonGroupPrimitive>
                    <div>
                        <IconChevronRight />
                    </div>
                    <div className="text-sm">Exception</div>
                </>
            ) : (
                <CategoryDropdown />
            )}
        </div>
    )
}

const CategoryDropdown = (): JSX.Element => {
    const { category, isViewingException } = useValues(errorTrackingIssueSceneLogic)
    const { setCategory, setExceptionsCategory } = useActions(errorTrackingIssueSceneLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive iconOnly={isViewingException} isSideActionRight={isViewingException} variant="outline">
                    {!isViewingException && exceptionTabLabel(category)}
                    <DropdownMenuOpenIndicator className="mx-1.5" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>

            <DropdownMenuContent loop align="start">
                <DropdownMenuGroup>
                    {!isViewingException && (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => {
                                    setCategory('exceptions')
                                    setExceptionsCategory('all')
                                }}
                                active={category === 'exceptions'}
                            >
                                {exceptionTabLabel('exceptions')}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => setCategory('breakdowns')}
                            active={category === 'breakdowns'}
                        >
                            {exceptionTabLabel('breakdowns')}
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => setCategory('autofix')}
                            active={category === 'autofix'}
                        >
                            {exceptionTabLabel('autofix')}
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => setCategory('similar_issues')}
                            active={category === 'similar_issues'}
                        >
                            {exceptionTabLabel('similar_issues')}
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
