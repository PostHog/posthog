import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { notebookRunLogic } from 'scenes/notebooks/Notebook/notebookRunLogic'

import { notebookAppLogic } from './notebookAppLogic'

export function NotebookAppPublicationChecks({
    shortId,
    sourceSavingReason,
}: {
    shortId: string
    sourceSavingReason?: string
}): JSX.Element {
    const logic = notebookAppLogic({ shortId })
    const { releaseReview, releaseReviewLoading, layout, savedNotebookLoading } = useValues(logic)
    const { checkRelease, restoreRelease, openSource } = useActions(logic)
    const { isRunning } = useValues(notebookRunLogic({ shortId }))
    return (
        <section className="border rounded p-3 mb-4" aria-label="Publication checks">
            <div className="flex flex-wrap gap-2 items-center justify-between">
                <strong>
                    {releaseReviewLoading
                        ? 'Checking sources…'
                        : releaseReview?.problems.length
                          ? 'Resolve these issues before publishing'
                          : releaseReview
                            ? 'Ready to publish'
                            : 'Publication checks'}
                </strong>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={
                            sourceSavingReason ||
                            (releaseReviewLoading || isRunning ? 'A check or run is in progress.' : undefined)
                        }
                        onClick={() => checkRelease(layout)}
                    >
                        Check again
                    </LemonButton>
                    {releaseReview?.has_previous && (
                        <LemonButton
                            size="small"
                            disabledReason={savedNotebookLoading ? 'Wait for the app to finish saving.' : undefined}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Restore the previous release?',
                                    description:
                                        'Viewers will see the preceding release. You can keep editing your current draft.',
                                    primaryButton: { children: 'Restore release', onClick: restoreRelease },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        >
                            Restore previous release
                        </LemonButton>
                    )}
                </div>
            </div>
            {releaseReview?.problems.length ? (
                <ul className="my-2">
                    {releaseReview.problems.map((problem, index) => (
                        <li key={index}>{problem}</li>
                    ))}
                </ul>
            ) : null}
            {releaseReview?.results_as_of && (
                <p className="text-secondary mb-0">
                    Oldest displayed result ran {new Date(releaseReview.results_as_of).toLocaleString()}.
                </p>
            )}
            {!!releaseReview?.dependencies?.length && (
                <details className="mt-2">
                    <summary className="cursor-pointer">Data dependencies</summary>
                    <ul>
                        {releaseReview.dependencies.map((cell) => (
                            <li key={cell.node_id}>
                                <LemonButton size="small" type="tertiary" onClick={() => openSource(cell.node_id)}>
                                    {cell.dataframe}
                                </LemonButton>
                                {cell.upstream.length > 0 && (
                                    <span className="text-secondary"> reads {cell.upstream.join(', ')}</span>
                                )}
                            </li>
                        ))}
                    </ul>
                </details>
            )}
        </section>
    )
}
