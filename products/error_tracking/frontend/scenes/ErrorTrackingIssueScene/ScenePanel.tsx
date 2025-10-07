import { useActions, useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconComment, IconShare } from '@posthog/icons'
import { LemonModal, Link, Spinner } from '@posthog/lemon-ui'

import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { SceneTextInput } from 'lib/components/Scenes/SceneTextInput'
import { SceneTextarea } from 'lib/components/Scenes/SceneTextarea'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonModalContent, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
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

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ScenePanelActionsSection, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from '../../components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from '../../components/Assignee/AssigneeSelect'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ExternalReferences } from '../../components/ExternalReferences'
import { StatusIndicator } from '../../components/Indicators'
import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { IssueTasks } from '../../components/IssueTasks'
import { RuntimeIcon } from '../../components/RuntimeIcon'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

const RESOURCE_TYPE = 'issue'

interface RelatedIssue {
    id: string
    title: string
    description?: string
    library?: string
}

const IssueModalContent = ({ issueId }: { issueId: string }): JSX.Element => {
    const logicProps: ErrorTrackingIssueSceneLogicProps = { id: issueId }
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(
        errorTrackingIssueSceneLogic(logicProps)
    )
    const tagRenderer = useErrorTagRenderer()

    return (
        <div className="ErrorTrackingIssue">
            <div className="space-y-2">
                <ExceptionCard
                    issue={issue ?? undefined}
                    issueLoading={issueLoading}
                    event={selectedEvent ?? undefined}
                    eventLoading={initialEventLoading}
                    label={tagRenderer(selectedEvent)}
                />
            </div>
        </div>
    )
}

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const hasTasks = useFeatureFlag('TASKS')
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const hasSimilarIssues = useFeatureFlag('ERROR_TRACKING_RELATED_ISSUES')
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    return issue ? (
        <div className="flex flex-col gap-2 @container">
            <ScenePanelActionsSection>
                <div className="grid grid-cols-2 gap-1">
                    <ButtonPrimitive
                        onClick={() => {
                            if (!hasDiscussions) {
                                posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                            }
                            openSidePanel(SidePanelTab.Discussion)
                        }}
                        tooltip="Comment"
                        menuItem
                        className="justify-center"
                    >
                        <IconComment />
                        <span className="hidden @[200px]:block">Comment</span>
                    </ButtonPrimitive>

                    <ButtonPrimitive
                        onClick={() => {
                            void copyToClipboard(
                                window.location.origin + urls.errorTrackingIssue(issue.id),
                                'issue link'
                            )
                        }}
                        tooltip="Share"
                        data-attr={`${RESOURCE_TYPE}-share`}
                        menuItem
                        className="justify-center"
                    >
                        <IconShare />
                        <span className="hidden @[200px]:block">Share</span>
                    </ButtonPrimitive>
                </div>
            </ScenePanelActionsSection>

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
            {hasSimilarIssues && <SimilarIssues />}
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

const SimilarIssues = (): JSX.Element => {
    const { issue, similarIssues, similarIssuesLoading } = useValues(errorTrackingIssueSceneLogic)
    const { loadSimilarIssues } = useActions(errorTrackingIssueSceneLogic)
    const { mergeIssues } = useAsyncActions(issueActionsLogic)
    const [selectedIssue, setSelectedIssue] = useState<RelatedIssue | null>(null)

    useEffect(() => {
        loadSimilarIssues()
    }, [loadSimilarIssues])

    const handleMerge = async (relatedIssueId: string): Promise<void> => {
        if (issue) {
            await mergeIssues([issue.id, relatedIssueId])
            loadSimilarIssues()
        }
    }

    return (
        <ScenePanelLabel title="Similar issues">
            {similarIssuesLoading ? (
                <Spinner />
            ) : similarIssues.length > 0 ? (
                <div className="flex flex-col gap-1">
                    {similarIssues.map((relatedIssue: RelatedIssue) => {
                        const relatedRuntime = getRuntimeFromLib(relatedIssue.library)
                        return (
                            <div
                                key={relatedIssue.id}
                                className="flex items-center justify-between px-2 py-1 border rounded bg-surface-primary"
                            >
                                <div
                                    className="flex flex-col gap-0.5 min-w-0 group flex-grow cursor-pointer"
                                    onClick={() => setSelectedIssue(relatedIssue)}
                                >
                                    <div className="font-medium flex items-center gap-2 text-sm truncate group-hover:text-accent">
                                        <RuntimeIcon runtime={relatedRuntime} fontSize="0.7rem" className="shrink-0" />
                                        {relatedIssue.title}
                                    </div>
                                    {relatedIssue.description && (
                                        <div className="text-xs text-secondary truncate">
                                            {relatedIssue.description}
                                        </div>
                                    )}
                                </div>
                                <ButtonPrimitive
                                    size="xxs"
                                    onClick={(e) => {
                                        e.preventDefault()
                                        handleMerge(relatedIssue.id)
                                    }}
                                    className="shrink-0 px-2 py-3 h-full"
                                >
                                    Merge
                                </ButtonPrimitive>
                            </div>
                        )
                    })}
                </div>
            ) : (
                <div className="text-sm text-gray-500">No similar issues found</div>
            )}

            {/* Issue Detail Modal */}
            <LemonModal isOpen={!!selectedIssue} onClose={() => setSelectedIssue(null)} width="95%" maxWidth="1400px">
                <LemonModalHeader>
                    <h3>{selectedIssue?.title || 'Issue Details'}</h3>
                </LemonModalHeader>
                <LemonModalContent>
                    {selectedIssue && <IssueModalContent issueId={selectedIssue.id} />}
                </LemonModalContent>
            </LemonModal>
        </ScenePanelLabel>
    )
}

const IssueFingerprints = (): JSX.Element => {
    const { issue, issueFingerprints, issueFingerprintsLoading } = useValues(errorTrackingIssueSceneLogic)
    return (
        <ScenePanelLabel title="Fingerprints">
            <Link to={issue ? urls.errorTrackingIssueFingerprints(issue.id) : undefined}>
                <ButtonPrimitive fullWidth menuItem variant="panel">
                    {issueFingerprintsLoading ? <Spinner /> : `${pluralize(issueFingerprints.length, 'fingerprint')}`}
                </ButtonPrimitive>
            </Link>
        </ScenePanelLabel>
    )
}
