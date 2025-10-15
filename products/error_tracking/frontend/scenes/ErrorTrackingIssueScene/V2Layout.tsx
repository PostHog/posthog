import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconShare } from '@posthog/icons'
import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    SelectPrimitive,
    SelectPrimitiveContent,
    SelectPrimitiveGroup,
    SelectPrimitiveItem,
    SelectPrimitiveLabel,
    SelectPrimitiveSeparator,
    SelectPrimitiveTrigger,
} from 'lib/ui/SelectPrimitive/SelectPrimitive'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SidePanelTab } from '~/types'

import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { isLastSeenException, useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import {
    ErrorTrackingIssueSceneCategory,
    ErrorTrackingIssueSceneExceptionsCategory,
    errorTrackingIssueSceneLogic,
} from './errorTrackingIssueSceneLogic'

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
                <div className="col-span-3 border-r flex flex-col min-h-0">
                    <div className="flex justify-between p-1">
                        <SceneBreadcrumbBackButton />
                        <div>
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
                        </div>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="p-2 space-y-2">
                        <ErrorTrackingIssueScenePanel showActions={false} />
                        <div className="bg-accent-3000 h-[100px] flex justify-center items-center">Breakdowns</div>
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
        <div className="bg-accent-3000 h-[500px] flex justify-center items-center">Breakdowns go here</div>
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
    const { category } = useValues(errorTrackingIssueSceneLogic)

    return (
        <div className="flex items-center gap-x-2 border bg-surface-tertiary py-1 px-2 rounded">
            <div>Issue</div>
            <div>/</div>
            <CategorySelect />
            {category === 'exceptions' && (
                <>
                    <div>/</div>
                    <ExceptionsCategorySelect />
                </>
            )}
        </div>
    )
}

const CategorySelect = (): JSX.Element => {
    const { category, exceptionsCategory, initialEvent } = useValues(errorTrackingIssueSceneLogic)
    const { setCategory, setExceptionsCategory, selectEvent } = useActions(errorTrackingIssueSceneLogic)

    const exceptions = category === 'exceptions'
    const exceptionsButNotAll = exceptions && exceptionsCategory != 'all'

    return (
        <div className="flex items-center">
            {exceptionsButNotAll && (
                <ButtonPrimitive
                    size="xs"
                    onClick={() => {
                        setCategory('exceptions')
                        setExceptionsCategory('all')
                    }}
                >
                    Exceptions
                </ButtonPrimitive>
            )}
            <SelectPrimitive
                value={category}
                onValueChange={(value) => {
                    if (['all', 'exception'].includes(value)) {
                        setCategory('exceptions')
                        setExceptionsCategory(value as ErrorTrackingIssueSceneExceptionsCategory)

                        if (initialEvent) {
                            selectEvent(initialEvent)
                        }

                        return
                    }
                    setCategory(value as ErrorTrackingIssueSceneCategory)
                }}
            >
                <SelectPrimitiveTrigger buttonProps={{ size: 'xs' }}>
                    {exceptionsButNotAll ? <></> : <span className="capitalize">{category}</span>}
                </SelectPrimitiveTrigger>
                <SelectPrimitiveContent matchTriggerWidth>
                    {!exceptions && (
                        <>
                            <SelectPrimitiveGroup>
                                <SelectPrimitiveLabel>Exceptions</SelectPrimitiveLabel>
                                <SelectPrimitiveItem value="all">All</SelectPrimitiveItem>
                                <SelectPrimitiveItem value="exception">Last seen</SelectPrimitiveItem>
                            </SelectPrimitiveGroup>
                            <SelectPrimitiveSeparator />
                        </>
                    )}
                    <SelectPrimitiveGroup>
                        <SelectPrimitiveItem value="breakdowns">Breakdowns</SelectPrimitiveItem>
                    </SelectPrimitiveGroup>
                </SelectPrimitiveContent>
            </SelectPrimitive>
        </div>
    )
}

const ExceptionsCategorySelect = (): JSX.Element => {
    const { exceptionsCategory, initialEvent, lastSeen, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    const { setExceptionsCategory, selectEvent } = useActions(errorTrackingIssueSceneLogic)

    const isLastSeenExceptionSelected = selectedEvent && isLastSeenException(lastSeen, selectedEvent)

    const label: string = {
        all: 'All',
        exception: isLastSeenExceptionSelected ? 'Last seen' : (selectedEvent?.uuid ?? 'Exception'),
    }[exceptionsCategory]

    return isLastSeenExceptionSelected ? (
        <div>{label}</div>
    ) : (
        <SelectPrimitive
            value={exceptionsCategory}
            onValueChange={(value) => {
                if (initialEvent) {
                    setExceptionsCategory(value === 'all' ? 'all' : 'exception')
                    selectEvent(initialEvent)
                }
            }}
        >
            <SelectPrimitiveTrigger buttonProps={{ size: 'xs' }}>
                <div>{label}</div>
            </SelectPrimitiveTrigger>
            <SelectPrimitiveContent matchTriggerWidth>
                {!isLastSeenExceptionSelected && selectedEvent ? (
                    <SelectPrimitiveItem value={selectedEvent.uuid}>{selectedEvent.uuid}</SelectPrimitiveItem>
                ) : null}
                {initialEvent && <SelectPrimitiveItem value={initialEvent.uuid}>Last seen</SelectPrimitiveItem>}
                <SelectPrimitiveItem value="all">All</SelectPrimitiveItem>
            </SelectPrimitiveContent>
        </SelectPrimitive>
    )
}
