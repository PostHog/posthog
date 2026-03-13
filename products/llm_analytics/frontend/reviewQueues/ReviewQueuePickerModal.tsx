import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInputSelect, LemonModal, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { reviewQueuePickerModalLogic, type ReviewQueuePickerModalProps } from './reviewQueuePickerModalLogic'

export function ReviewQueuePickerModal({
    confirmLabel = 'Add to queue',
    title = 'Add traces to queue',
    ...props
}: ReviewQueuePickerModalProps): JSX.Element {
    const logic = useMountedLogic(reviewQueuePickerModalLogic(props))
    const { setSelectedQueueKey, setTraceIdsInput, submit } = useActions(logic)
    const {
        queues,
        queuesLoading,
        selectedQueueValue,
        selectedQueue,
        isCreatingQueue,
        traceIdsInput,
        parsedTraceIds,
        isSubmitting,
    } = useValues(logic)

    return (
        <LemonModal isOpen onClose={() => props.onClose?.()} simple maxWidth="36rem">
            <LemonModalHeader>{title}</LemonModalHeader>

            <LemonModalContent className="space-y-4">
                <div className="space-y-2">
                    <div className="text-sm font-medium">Queue</div>
                    <LemonInputSelect<string>
                        mode="single"
                        value={selectedQueueValue}
                        onChange={(values) => setSelectedQueueKey(values[0] ? String(values[0]) : null)}
                        options={queues.results.map((queue) => ({
                            key: queue.id,
                            value: queue.id,
                            label: queue.name,
                            labelComponent: (
                                <div className="flex items-center justify-between gap-3 min-w-0">
                                    <span className="truncate">{queue.name}</span>
                                    <span className="shrink-0 text-xs text-muted">
                                        {queue.pending_item_count} pending
                                    </span>
                                </div>
                            ),
                        }))}
                        allowCustomValues
                        formatCreateLabel={(input) => `Create queue "${input.trim()}"`}
                        placeholder="Select a queue or create one"
                        fullWidth
                        emptyStateComponent={
                            <div className="px-3 py-2 text-sm text-muted">
                                {queuesLoading ? (
                                    <div className="flex items-center gap-2">
                                        <Spinner textColored />
                                        <span>Loading queues...</span>
                                    </div>
                                ) : (
                                    'No queues yet. Type a name to create the first one.'
                                )}
                            </div>
                        }
                    />
                    <div className="text-xs text-muted">
                        {isCreatingQueue
                            ? 'A new queue will be created when you submit.'
                            : selectedQueue
                              ? `${selectedQueue.pending_item_count} pending traces in this queue.`
                              : 'Choose an existing queue or create one inline.'}
                    </div>
                </div>

                <div className="space-y-2">
                    <div className="text-sm font-medium">Trace IDs</div>
                    <LemonTextArea
                        value={traceIdsInput}
                        onChange={(value) => setTraceIdsInput(value)}
                        placeholder="Paste one or more trace IDs"
                        rows={8}
                        className="font-mono text-xs"
                        data-attr="review-queue-trace-ids-input"
                    />
                    <div className="text-xs text-muted">
                        Separate trace IDs with new lines, commas, or spaces. {parsedTraceIds.length} ready to add.
                    </div>
                </div>
            </LemonModalContent>

            <LemonModalFooter>
                <LemonButton type="secondary" onClick={() => props.onClose?.()} disabled={isSubmitting}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => submit()}
                    loading={isSubmitting}
                    data-attr="review-queue-submit-button"
                >
                    {confirmLabel}
                </LemonButton>
            </LemonModalFooter>
        </LemonModal>
    )
}
