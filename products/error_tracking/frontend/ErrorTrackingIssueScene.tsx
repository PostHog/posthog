import './ErrorTracking.scss'

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

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ErrorTrackingIssueScenePanel } from './ErrorTrackingIssueScenePanel'
import { ErrorFilters } from './components/ErrorFilters'
import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { EventsTable } from './components/EventsTable/EventsTable'
import { ExceptionCard } from './components/ExceptionCard'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { useErrorTagRenderer } from './hooks/use-error-tag-renderer'
import { Metadata } from './issue/Metadata'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
    suppressed: 'Suppressed',
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueId, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')

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
            <div className="ErrorTracking grid grid-cols-4 gap-4">
                <div className="space-y-2 col-span-3">
                    <ExceptionCard
                        issue={issue ?? undefined}
                        issueLoading={issueLoading}
                        event={selectedEvent ?? undefined}
                        eventLoading={initialEventLoading}
                        label={tagRenderer(selectedEvent)}
                    />
                    <ErrorFilters.Root>
                        <ErrorFilters.DateRange />
                        <ErrorFilters.FilterGroup />
                        <ErrorFilters.InternalAccounts />
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
