import { useActions, useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonModalContent, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SimilarIssue } from '~/queries/schema/schema-general'

import { ExceptionCard } from '../../../components/ExceptionCard'
import { issueActionsLogic } from '../../../components/IssueActions/issueActionsLogic'
import SimilarIssueCard from '../../../components/SimilarIssueCard'
import { useErrorTagRenderer } from '../../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export const SimilarIssuesList = (): JSX.Element => {
    const { issue, similarIssues, similarIssuesLoading, similarIssuesMaxDistance } =
        useValues(errorTrackingIssueSceneLogic)
    const { loadSimilarIssues, setSimilarIssuesMaxDistance } = useActions(errorTrackingIssueSceneLogic)
    const { mergeIssues } = useAsyncActions(issueActionsLogic)
    const [selectedIssue, setSelectedIssue] = useState<SimilarIssue | null>(null)

    useEffect(() => {
        loadSimilarIssues()
    }, [loadSimilarIssues])

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
        <>
            {similarIssuesLoading ? (
                <Spinner />
            ) : similarIssues.length > 0 ? (
                <div className="flex flex-col gap-1">
                    {similarIssues.map((similarIssue: SimilarIssue) => {
                        return (
                            <SimilarIssueCard
                                issue={similarIssue}
                                onClick={() => setSelectedIssue(similarIssue)}
                                actions={
                                    <ButtonPrimitive
                                        size="xxs"
                                        onClick={() => handleMerge(similarIssue.id, similarIssuesMaxDistance)}
                                        className="shrink-0 px-2 py-3 h-full"
                                    >
                                        Merge
                                    </ButtonPrimitive>
                                }
                            />
                        )
                    })}
                </div>
            ) : (
                <div className="flex items-center gap-2 text-sm text-gray-500">
                    <LemonButton size="small" onClick={increaseMaxDistance} className="w-fit" type="primary">
                        No similar issues found. Search further?
                    </LemonButton>
                </div>
            )}

            {/* Issue Detail Modal */}
            <LemonModal isOpen={!!selectedIssue} onClose={() => setSelectedIssue(null)} width="95%" maxWidth="1400px">
                <LemonModalHeader>
                    <h3>{selectedIssue?.name || 'Issue Details'}</h3>
                </LemonModalHeader>
                <LemonModalContent>
                    {selectedIssue && <IssueModalContent issueId={selectedIssue.id} />}
                </LemonModalContent>
            </LemonModal>
        </>
    )
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
