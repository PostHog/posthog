import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { notebookAppLogic } from './notebookAppLogic'
import { NotebookLaunchReviewForm } from './NotebookLaunchReviewForm'

export function NotebookAppTemplateModal({
    shortId,
    emptyApp,
    onClose,
}: {
    shortId: string
    emptyApp: boolean
    onClose: () => void
}): JSX.Element {
    const [configuringReview, setConfiguringReview] = useState(false)
    const { savedNotebookLoading } = useValues(notebookAppLogic({ shortId }))
    return (
        <LemonModal simple onClose={onClose} closable={!savedNotebookLoading}>
            <LemonModal.Header>
                <h3>{configuringReview ? 'Feature launch review' : 'Choose a template'}</h3>
            </LemonModal.Header>
            {configuringReview ? (
                <NotebookLaunchReviewForm
                    shortId={shortId}
                    emptyApp={emptyApp}
                    saving={savedNotebookLoading}
                    onClose={onClose}
                />
            ) : (
                <LemonModal.Content>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        aria-label="Feature launch review"
                        aria-describedby="notebook-launch-review-description"
                        sideIcon={<IconChevronRight />}
                        data-attr="notebook-launch-review-start"
                        onClick={() => {
                            setConfiguringReview(true)
                            posthog.capture('notebook app launch review started', { short_id: shortId })
                        }}
                    >
                        <span className="flex flex-col gap-1 py-1">
                            <strong>Feature launch review</strong>
                            <span className="font-normal text-secondary" id="notebook-launch-review-description">
                                Find where people drop off for a selected flag value, then watch their recordings.
                            </span>
                        </span>
                    </LemonButton>
                </LemonModal.Content>
            )}
        </LemonModal>
    )
}
