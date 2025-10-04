import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueId, issueLoading, selectedEvent, initialEventLoading, eventsQuery, eventsQueryKey } =
        useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')

    const isPostHogSDKIssue = selectedEvent?.properties.$exception_values?.some((v: string) =>
        v.includes('persistence.isDisabled is not a function')
    )

    return (
        <ErrorTrackingSetupPrompt>
            <div className="flex justify-between mb-2 -ml-[var(--button-padding-x-lg)]">
                <SceneBreadcrumbBackButton />
                {hasIssueSplitting && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <ButtonPrimitive iconOnly>
                                <IconEllipsis />
                            </ButtonPrimitive>
                        </DropdownMenuTrigger>

                        <DropdownMenuContent loop align="end">
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive
                                    size="base"
                                    menuItem
                                    onClick={() => router.actions.push(urls.errorTrackingIssueFingerprints(issueId))}
                                >
                                    Split issue
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </div>

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

            <div className="ErrorTrackingIssue grid grid-cols-4 gap-4">
                <div className="space-y-2 col-span-3">
                    <ExceptionCard
                        issue={issue ?? undefined}
                        issueLoading={issueLoading}
                        event={selectedEvent ?? undefined}
                        eventLoading={initialEventLoading}
                        label={tagRenderer(selectedEvent)}
                    />
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
                            selectedEvent={selectedEvent}
                            onEventSelect={(selectedEvent) => (selectedEvent ? selectEvent(selectedEvent) : null)}
                        />
                    </Metadata>
                </div>
                <ErrorTrackingIssueScenePanel />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}
