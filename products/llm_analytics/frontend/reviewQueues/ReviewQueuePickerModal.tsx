import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonDropdown, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { reviewQueuePickerModalLogic, type ReviewQueuePickerModalProps } from './reviewQueuePickerModalLogic'

export function ReviewQueuePickerModal({
    confirmLabel = 'Add to queue',
    buttonType = 'secondary',
    buttonSize = 'small',
    ...props
}: ReviewQueuePickerModalProps & {
    buttonType?: 'primary' | 'secondary' | 'tertiary'
    buttonSize?: 'xsmall' | 'small' | 'medium'
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [search, setSearch] = useState('')
    const logic = useMountedLogic(
        reviewQueuePickerModalLogic({
            ...props,
            onClose: () => {
                setIsOpen(false)
                props.onClose?.()
            },
        })
    )
    const { setSelectedQueueKey, submit } = useActions(logic)
    const { queues, queuesLoading, isSubmitting } = useValues(logic)
    const normalizedSearch = search.trim().toLowerCase()
    const filteredQueues = normalizedSearch
        ? queues.results.filter((queue) => queue.name.toLowerCase().includes(normalizedSearch))
        : queues.results
    const hasExactQueueMatch = queues.results.some((queue) => queue.name.trim().toLowerCase() === normalizedSearch)
    const canCreateQueue = !!normalizedSearch && !hasExactQueueMatch

    const overlay = (
        <div className="w-xs">
            <LemonInput
                value={search}
                onChange={setSearch}
                placeholder="Find a queue"
                autoFocus
                disabled={isSubmitting}
                data-attr="llma-review-queue-search"
            />
            <LemonDivider className="my-0 mt-2" />
            <div className="max-h-64 overflow-y-auto py-2 space-y-2">
                {queuesLoading ? (
                    <>
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                    </>
                ) : filteredQueues.length > 0 ? (
                    filteredQueues.map((queue) => (
                        <LemonButton
                            key={queue.id}
                            fullWidth
                            size="small"
                            disabled={isSubmitting}
                            onClick={() => {
                                setSelectedQueueKey(queue.id)
                                submit(queue.id)
                            }}
                            data-attr="llma-review-queue-select"
                        >
                            <span className="line-clamp-1">{queue.name}</span>
                        </LemonButton>
                    ))
                ) : (
                    <p className="px-2 text-sm text-muted">
                        {normalizedSearch ? 'No queues found.' : 'No queues yet.'}
                    </p>
                )}
            </div>
            <LemonDivider className="my-0 mb-2" />
            <LemonButton
                fullWidth
                size="small"
                type="secondary"
                disabled={!canCreateQueue || isSubmitting}
                onClick={() => {
                    submit(search.trim())
                }}
                data-attr="llma-review-queue-create"
            >
                {canCreateQueue ? `Create "${search.trim()}"` : 'Type a queue name to create one'}
            </LemonButton>
        </div>
    )

    return (
        <LemonDropdown
            overlay={overlay}
            visible={isOpen}
            onVisibilityChange={(nextOpen) => {
                setIsOpen(nextOpen)

                if (!nextOpen) {
                    setSearch('')
                }
            }}
            closeOnClickInside={false}
        >
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type={buttonType}
                    size={buttonSize}
                    onClick={() => setIsOpen(!isOpen)}
                    loading={isSubmitting}
                    data-attr="llma-trace-add-to-queue-button"
                >
                    {confirmLabel}
                </LemonButton>
            </AccessControlAction>
        </LemonDropdown>
    )
}
