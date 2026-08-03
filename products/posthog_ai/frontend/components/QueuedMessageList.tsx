import { useEffect, useRef, useState } from 'react'

import { IconCheck, IconPencil, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import type { QueuedMessage } from '../logics/runInteractionLogic'

export interface QueuedMessageListProps {
    messages: QueuedMessage[]
    onUpdate: (id: string, content: string) => void
    onRemove: (id: string) => void
}

interface QueuedMessageItemProps {
    message: QueuedMessage
    isEditing: boolean
    onEdit: () => void
    onCancel: () => void
    onSave: (id: string, content: string) => void
    onRemove: (id: string) => void
}

/** One staged "Up next" message — read row with edit/remove, or an inline editor. Logic-free (controlled). */
function QueuedMessageItem({
    message,
    isEditing,
    onEdit,
    onCancel,
    onSave,
    onRemove,
}: QueuedMessageItemProps): JSX.Element {
    const [draft, setDraft] = useState(message.content)
    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    useEffect(() => {
        setDraft(message.content)
    }, [message.content])

    useEffect(() => {
        if (isEditing) {
            textAreaRef.current?.focus()
            textAreaRef.current?.select()
        }
    }, [isEditing])

    const canSave = draft.trim().length > 0

    if (isEditing) {
        return (
            <div className="space-y-2">
                <LemonTextArea
                    ref={textAreaRef}
                    value={draft}
                    onChange={setDraft}
                    minRows={1}
                    maxRows={4}
                    autoFocus
                    onPressCmdEnter={() => {
                        if (canSave) {
                            onSave(message.id, draft)
                        }
                    }}
                />
                <div className="flex gap-1">
                    <LemonButton
                        size="xsmall"
                        icon={<IconCheck />}
                        onClick={() => onSave(message.id, draft)}
                        disabledReason={canSave ? undefined : 'Message cannot be empty'}
                    >
                        Save
                    </LemonButton>
                    <LemonButton size="xsmall" type="secondary" icon={<IconX />} onClick={onCancel}>
                        Cancel
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="group flex items-center gap-2 py-1 px-2 rounded-md hover:bg-bg-light">
            <p className="flex-1 text-sm text-secondary truncate mb-0">{message.content}</p>
            <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconPencil className="text-muted" />}
                    onClick={onEdit}
                    tooltip="Edit message"
                />
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconTrash className="text-muted" />}
                    onClick={() => onRemove(message.id)}
                    tooltip="Remove from queue"
                />
            </div>
        </div>
    )
}

/**
 * The editable "Up next" buffer rendered above the composer while the agent is busy. Purely presentational
 * (no kea): the consumer owns the queue state and passes `onUpdate` / `onRemove`. Modeled on PostHog AI's
 * `QueuedMessageItem`, minus the conversation/Max coupling.
 */
export function QueuedMessageList({ messages, onUpdate, onRemove }: QueuedMessageListProps): JSX.Element | null {
    const [editingId, setEditingId] = useState<string | null>(null)

    if (messages.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-0.5 pb-2">
            <p className="text-xs font-medium text-muted px-2 mb-0">Up next</p>
            {messages.map((message) => (
                <QueuedMessageItem
                    key={message.id}
                    message={message}
                    isEditing={editingId === message.id}
                    onEdit={() => setEditingId(message.id)}
                    onCancel={() => setEditingId(null)}
                    onSave={(id, content) => {
                        onUpdate(id, content)
                        setEditingId(null)
                    }}
                    onRemove={onRemove}
                />
            ))}
        </div>
    )
}
