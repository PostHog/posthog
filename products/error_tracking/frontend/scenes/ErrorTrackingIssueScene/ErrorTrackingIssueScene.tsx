import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'

import { PageHeader } from 'lib/components/PageHeader'
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
    const { issue, issueId, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    return (
        <ErrorTrackingSetupPrompt>
            {hasIssueSplitting && (
                <PageHeader
                    buttons={
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <ButtonPrimitive iconOnly>
                                    <IconEllipsis />
                                </ButtonPrimitive>
                            </DropdownMenuTrigger>

                            <DropdownMenuContent loop>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive
                                        size="base"
                                        menuItem
                                        onClick={() =>
                                            router.actions.push(urls.errorTrackingIssueFingerprints(issueId))
                                        }
                                    >
                                        Split issue
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    }
                />
            )}
            {newSceneLayout && (
                <div className="mb-2 -ml-[var(--button-padding-x-lg)]">
                    <SceneBreadcrumbBackButton />
                </div>
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
                            issueId={issueId}
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
