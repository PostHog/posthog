import { useActions, useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconSearch, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonModalContent, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { SimilarIssue } from '~/queries/schema/schema-general'

import { ExceptionCard } from '../../../components/ExceptionCard'
import { issueActionsLogic } from '../../../components/IssueActions/issueActionsLogic'
import SimilarIssueCard, { MergeAction } from '../../../components/SimilarIssueCard'
import { StyleVariables } from '../../../components/StyleVariables'
import { useErrorTagRenderer } from '../../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export const SimilarIssuesList = (): JSX.Element => {
    const { issue, similarIssues, similarIssuesLoading, similarIssuesMaxDistance, similarIssuesError } =
        useValues(errorTrackingIssueSceneLogic)
    const { loadSimilarIssues, setSimilarIssuesMaxDistance } = useActions(errorTrackingIssueSceneLogic)
    const { mergeIssues } = useAsyncActions(issueActionsLogic)
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const [selectedIssue, setSelectedIssue] = useState<SimilarIssue | null>(null)

    useEffect(() => {
        if (dataProcessingAccepted) {
            loadSimilarIssues()
        }
    }, [loadSimilarIssues, dataProcessingAccepted])

    const handleMerge = async (relatedIssueId: string, maxDistance: number): Promise<void> => {
        if (issue) {
            await mergeIssues([issue.id, relatedIssueId])
            posthog.capture('similar_issue_merged', { maxDistance: maxDistance })
            loadSimilarIssues(true)
        }
    }

    const increaseMaxDistance = (): void => {
        setSimilarIssuesMaxDistance(similarIssuesMaxDistance + 0.1)
    }

    return (
        <div className="flex flex-col h-full min-h-0">
            {!dataProcessingAccepted ? (
                <EmptyState
                    title="AI data processing required"
                    description="Similar issue search uses AI embeddings to find related issues. Enable AI data processing for your organization to use this feature."
                    action={
                        <LemonButton
                            type="primary"
                            size="small"
                            to={urls.settings('organization-details', 'organization-ai-consent')}
                        >
                            Go to organization settings
                        </LemonButton>
                    }
                />
            ) : similarIssuesLoading ? (
                <Spinner className="m-auto" />
            ) : similarIssuesError ? (
                <EmptyState
                    icon={<IconWarning className="text-warning text-3xl" />}
                    title="Embeddings not available"
                    description="No embeddings have been generated for this issue yet. Embeddings may still be processing, please try again later."
                    action={
                        <LemonButton type="primary" size="small" onClick={() => loadSimilarIssues(true)}>
                            Retry
                        </LemonButton>
                    }
                />
            ) : similarIssues.length > 0 ? (
                <div className="flex flex-col gap-1 divide-y overflow-y-auto flex-1 min-h-0" tabIndex={-1}>
                    {similarIssues.map((similarIssue: SimilarIssue) => {
                        return (
                            <SimilarIssueCard
                                key={similarIssue.id}
                                issue={similarIssue}
                                onClick={() => setSelectedIssue(similarIssue)}
                                actions={
                                    <MergeAction
                                        onClick={() => handleMerge(similarIssue.id, similarIssuesMaxDistance)}
                                    />
                                }
                            />
                        )
                    })}
                </div>
            ) : (
                <EmptyState
                    title="No similar issues found"
                    description="No issues within the current search distance match this issue. Try expanding the search range to find more distant matches."
                    action={
                        <LemonButton type="primary" size="small" onClick={increaseMaxDistance}>
                            Search further
                        </LemonButton>
                    }
                />
            )}

            {/* Issue Detail Modal */}
            <LemonModal
                isOpen={!!selectedIssue}
                onClose={() => setSelectedIssue(null)}
                width="95%"
                maxWidth="1400px"
                className="h-[80vh]"
                simple
            >
                <LemonModalHeader className="shrink-0">
                    <h3>{selectedIssue?.name || 'Issue Details'}</h3>
                </LemonModalHeader>
                <LemonModalContent embedded className="flex-1 flex flex-col min-h-0 !overflow-y-hidden">
                    {selectedIssue && <IssueModalContent issueId={selectedIssue.id} />}
                </LemonModalContent>
            </LemonModal>
        </div>
    )
}

const EmptyState = ({
    icon,
    title,
    description,
    action,
}: {
    icon?: JSX.Element
    title: string
    description: string
    action: JSX.Element
}): JSX.Element => {
    return (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 p-6 text-center">
            {icon ?? <IconSearch className="text-secondary text-3xl" />}
            <div className="flex flex-col gap-1">
                <h4 className="font-semibold mb-0">{title}</h4>
                <p className="text-secondary text-sm max-w-80 mb-0">{description}</p>
            </div>
            {action}
        </div>
    )
}

const IssueModalContent = ({ issueId }: { issueId: string }): JSX.Element => {
    const logicProps: ErrorTrackingIssueSceneLogicProps = { id: issueId }
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(
        errorTrackingIssueSceneLogic(logicProps)
    )
    const tagRenderer = useErrorTagRenderer()

    return (
        <StyleVariables className="ErrorTrackingIssue flex-1 min-h-0 flex flex-col">
            <ExceptionCard
                issueId={issueId}
                issueName={issue?.name ?? null}
                loading={issueLoading || initialEventLoading}
                event={selectedEvent ?? undefined}
                label={tagRenderer(selectedEvent)}
            />
        </StyleVariables>
    )
}
