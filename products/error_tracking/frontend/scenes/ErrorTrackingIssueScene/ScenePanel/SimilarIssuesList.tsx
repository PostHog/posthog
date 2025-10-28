import { useActions, useAsyncActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonModalContent, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { SimilarIssue } from '~/queries/schema/schema-general'

import { ExceptionCard } from '../../../components/ExceptionCard'
import { issueActionsLogic } from '../../../components/IssueActions/issueActionsLogic'
import SimilarIssueCard from '../../../components/SimilarIssueCard'
import { useErrorTagRenderer } from '../../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export const SimilarIssuesList = (): JSX.Element => {
    const { issue, similarIssues, similarIssuesLoading } = useValues(errorTrackingIssueSceneLogic)
    const { loadSimilarIssues } = useActions(errorTrackingIssueSceneLogic)
    const { mergeIssues } = useAsyncActions(issueActionsLogic)
    const [selectedIssue, setSelectedIssue] = useState<SimilarIssue | null>(null)

    useEffect(() => {
        loadSimilarIssues()
    }, [loadSimilarIssues])

    const handleMerge = async (relatedIssueId: string): Promise<void> => {
        if (issue) {
            await mergeIssues([issue.id, relatedIssueId])
            loadSimilarIssues(true)
        }
    }

    return (
        <ScenePanelLabel title="Similar issues">
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
                                        onClick={() => handleMerge(similarIssue.id)}
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
                <div className="text-sm text-gray-500">No similar issues found</div>
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
        </ScenePanelLabel>
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
