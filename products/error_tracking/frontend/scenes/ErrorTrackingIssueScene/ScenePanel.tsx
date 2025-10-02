import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonModal, Link, Spinner } from '@posthog/lemon-ui'

// import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneTextInput } from 'lib/components/Scenes/SceneTextInput'
import { SceneTextarea } from 'lib/components/Scenes/SceneTextarea'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { pluralize } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { ScenePanelCommonActions, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../components/Assignee/AssigneeSelect'
// import { RuntimeIcon } from '../../components/RuntimeIcon'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ExternalReferences } from '../../components/ExternalReferences'
import { StatusIndicator } from '../../components/Indicators'
import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { IssueTasks } from '../../components/IssueTasks'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

const RESOURCE_TYPE = 'issue'

interface RelatedIssue {
    id: string
    title: string
    description?: string
}

const IssueModalContent = ({ issueId }: { issueId: string }): JSX.Element => {
    const logicProps: ErrorTrackingIssueSceneLogicProps = { id: issueId }
    const logic = errorTrackingIssueSceneLogic(logicProps)
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(logic)
    const { selectEvent } = useActions(logic)
    const tagRenderer = useErrorTagRenderer()

    return (
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
            <div className="col-span-1">
                <ErrorTrackingIssueScenePanel />
            </div>
        </div>
    )
}

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const hasTasks = useFeatureFlag('TASKS')
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const hasRelatedIssues = useFeatureFlag('ERROR_TRACKING_RELATED_ISSUES')

    return issue ? (
        <div className="flex flex-col gap-2">
            <ScenePanelCommonActions>
                <SceneCommonButtons
                    comment
                    share={{
                        onClick: () => {
                            void copyToClipboard(
                                window.location.origin + urls.errorTrackingIssue(issue.id),
                                'issue link'
                            )
                        },
                    }}
                    dataAttrKey={RESOURCE_TYPE}
                />
            </ScenePanelCommonActions>

            <ScenePanelDivider />

            <SceneTextInput
                name="name"
                defaultValue={issue.name ?? ''}
                onSave={updateName}
                dataAttrKey={RESOURCE_TYPE}
            />
            <SceneTextarea
                name="description"
                defaultValue={issue.description ?? ''}
                onSave={updateDescription}
                dataAttrKey={RESOURCE_TYPE}
            />

            <IssueStatusSelect status={issue.status} onChange={updateStatus} />
            <IssueAssigneeSelect
                assignee={issue.assignee}
                onChange={updateAssignee}
                disabled={issue.status != 'active'}
            />
            <IssueExternalReference />
            {hasIssueSplitting && <IssueFingerprints />}
            {hasTasks && <IssueTasks />}
            <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
            {hasRelatedIssues && <RelatedIssues />}
        </div>
    ) : null
}

const IssueStatusSelect = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    return (
        <ScenePanelLabel title="Status">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive fullWidth className="flex justify-between" variant="panel" menuItem>
                        <StatusIndicator status={status} withTooltip={true} />
                        <DropdownMenuOpenIndicator />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>

                <DropdownMenuContent loop matchTriggerWidth>
                    {status === 'active' ? (
                        <>
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={() => onChange('resolved')}>
                                    <StatusIndicator status="resolved" intent />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive menuItem onClick={() => onChange('suppressed')}>
                                    <StatusIndicator status="suppressed" intent />
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        </>
                    ) : (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive menuItem onClick={() => onChange('active')}>
                                <StatusIndicator status="active" intent />
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </ScenePanelLabel>
    )
}

const IssueAssigneeSelect = ({
    assignee,
    disabled,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    disabled: boolean
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    return (
        <ScenePanelLabel title="Assignee">
            <AssigneeSelect assignee={assignee} onChange={onChange}>
                {(anyAssignee, isOpen) => (
                    <ButtonPrimitive
                        menuItem
                        fullWidth
                        disabled={disabled}
                        className="flex justify-between"
                        data-state={isOpen ? 'open' : 'closed'}
                        variant="panel"
                    >
                        <div className="flex items-center">
                            <AssigneeIconDisplay assignee={anyAssignee} size="small" />
                            <AssigneeLabelDisplay assignee={anyAssignee} className="ml-1" size="small" />
                        </div>
                        {!disabled && <DropdownMenuOpenIndicator />}
                    </ButtonPrimitive>
                )}
            </AssigneeSelect>
        </ScenePanelLabel>
    )
}

const IssueExternalReference = (): JSX.Element => {
    return (
        <ScenePanelLabel title="External references">
            <ExternalReferences />
        </ScenePanelLabel>
    )
}

const RelatedIssues = (): JSX.Element => {
    const { issue, relatedIssues, relatedIssuesLoading } = useValues(errorTrackingIssueSceneLogic)
    const { loadRelatedIssues } = useActions(errorTrackingIssueSceneLogic)
    const { mergeIssues } = useActions(issueActionsLogic)
    const [selectedIssue, setSelectedIssue] = useState<RelatedIssue | null>(null)

    useEffect(() => {
        loadRelatedIssues()
    }, [loadRelatedIssues])

    const handleMerge = async (relatedIssueId: string): Promise<void> => {
        if (issue) {
            await mergeIssues([issue.id, relatedIssueId])
            loadRelatedIssues()
        }
    }

    return (
        <ScenePanelLabel title="Related issues">
            {relatedIssuesLoading ? (
                <Spinner />
            ) : relatedIssues.length > 0 ? (
                <div className="flex flex-col gap-1">
                    {relatedIssues.map((relatedIssue: RelatedIssue) => {
                        // const relatedRuntime = getRuntimeFromLib(relatedIssue.library)
                        return (
                            <div
                                key={relatedIssue.id}
                                className="flex items-center justify-between p-2 border rounded hover:bg-gray-50"
                            >
                                <div
                                    className="flex-1 min-w-0 cursor-pointer"
                                    onClick={() => setSelectedIssue(relatedIssue)}
                                >
                                    <div className="flex items-center gap-2">
                                        {/* <span className="shrink-0 text-gray-600">
                                            <RuntimeIcon runtime={relatedRuntime} fontSize="0.7rem" />
                                        </span> */}
                                        <div className="font-medium text-sm truncate text-link hover:underline">
                                            {relatedIssue.title}
                                        </div>
                                    </div>
                                    {relatedIssue.description && (
                                        <div className="text-xs text-gray-600 truncate">{relatedIssue.description}</div>
                                    )}
                                </div>
                                <ButtonPrimitive
                                    size="xs"
                                    variant="outline"
                                    onClick={(e) => {
                                        e.preventDefault()
                                        handleMerge(relatedIssue.id)
                                    }}
                                    className="ml-2 shrink-0"
                                >
                                    Merge
                                </ButtonPrimitive>
                            </div>
                        )
                    })}
                </div>
            ) : (
                <div className="text-sm text-gray-500">No related issues found</div>
            )}

            {/* Issue Detail Modal */}
            <LemonModal isOpen={!!selectedIssue} onClose={() => setSelectedIssue(null)} width="95%" maxWidth="1400px">
                <LemonModalHeader>
                    <h3>{selectedIssue?.title || 'Issue Details'}</h3>
                </LemonModalHeader>
                <LemonModalContent>
                    {selectedIssue && <IssueModalContent issueId={selectedIssue.id} />}
                </LemonModalContent>
                <LemonModalFooter>
                    <div className="flex gap-2">
                        <Link
                            to={urls.errorTrackingIssue(selectedIssue?.id || '')}
                            className="text-link hover:underline"
                            onClick={() => setSelectedIssue(null)}
                        >
                            Open in New Tab
                        </Link>
                        <ButtonPrimitive variant="secondary" onClick={() => setSelectedIssue(null)}>
                            Close
                        </ButtonPrimitive>
                    </div>
                </LemonModalFooter>
            </LemonModal>
        </ScenePanelLabel>
    )
}

const IssueFingerprints = (): JSX.Element => {
    const { issue, issueFingerprints, issueFingerprintsLoading } = useValues(errorTrackingIssueSceneLogic)
    const { loadIssueFingerprints } = useActions(errorTrackingIssueSceneLogic)

    useEffect(() => {
        loadIssueFingerprints()
    }, [loadIssueFingerprints])

    return (
        <ScenePanelLabel title="Fingerprints">
            <Link to={issue ? urls.errorTrackingIssueFingerprints(issue.id) : undefined}>
                <ButtonPrimitive fullWidth>
                    {issueFingerprintsLoading ? <Spinner /> : `${pluralize(issueFingerprints.length, 'fingerprint')}`}
                </ButtonPrimitive>
            </Link>
        </ScenePanelLabel>
    )
}
