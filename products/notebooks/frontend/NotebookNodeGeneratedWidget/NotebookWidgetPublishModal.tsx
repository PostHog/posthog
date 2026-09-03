import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import {
    NotebookNodeGeneratedWidgetLogicProps,
    notebookNodeGeneratedWidgetLogic,
} from './notebookNodeGeneratedWidgetLogic'

export function NotebookWidgetPublishModal(props: NotebookNodeGeneratedWidgetLogicProps): JSX.Element {
    const logic = notebookNodeGeneratedWidgetLogic(props)
    const { publishDescription, publishError, publishInFlight, publishModalOpen, publishName, publishTags } =
        useValues(logic)
    const { closePublishModal, publishReusableWidget, setPublishDescription, setPublishName, setPublishTags } =
        useActions(logic)

    return (
        <LemonModal
            isOpen={publishModalOpen}
            onClose={closePublishModal}
            title="Convert to reusable widget"
            description="This publishes the widget to your project and saves a small snapshot of its current inputs as demo data."
            footer={
                <>
                    <LemonButton onClick={closePublishModal}>Cancel</LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={publishReusableWidget}
                        loading={publishInFlight}
                        disabledReason={!publishName.trim() ? 'Add a widget name.' : undefined}
                    >
                        Make reusable
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div>
                    <LemonLabel htmlFor={`reusable-widget-name-${props.nodeId}`}>Name</LemonLabel>
                    <LemonInput
                        id={`reusable-widget-name-${props.nodeId}`}
                        value={publishName}
                        onChange={setPublishName}
                        maxLength={400}
                        autoFocus
                        className="mt-1"
                    />
                </div>
                <div>
                    <LemonLabel htmlFor={`reusable-widget-description-${props.nodeId}`}>Description</LemonLabel>
                    <LemonTextArea
                        id={`reusable-widget-description-${props.nodeId}`}
                        value={publishDescription}
                        onChange={setPublishDescription}
                        placeholder="Describe what this widget shows and when to use it."
                        maxLength={2000}
                        minRows={3}
                        className="mt-1"
                    />
                </div>
                <div>
                    <LemonLabel htmlFor={`reusable-widget-tags-${props.nodeId}`}>Tags</LemonLabel>
                    <LemonInput
                        id={`reusable-widget-tags-${props.nodeId}`}
                        value={publishTags}
                        onChange={setPublishTags}
                        placeholder="Revenue, plans, comparison"
                        className="mt-1"
                    />
                    <div className="mt-1 text-xs text-muted">Separate tags with commas.</div>
                </div>
                <LemonBanner type="info">
                    This copies up to 20 rows from each current input into a project-scoped demo. Check that the sample
                    is suitable for everyone with access to this project. Unpinned instances will follow new versions
                    automatically.
                </LemonBanner>
                {publishError ? <LemonBanner type="error">{publishError}</LemonBanner> : null}
            </div>
        </LemonModal>
    )
}
