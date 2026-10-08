import { useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconCheck, IconChevronDown, IconPencil, IconStack, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { cn } from 'lib/utils/css-classes'

import type { QueuedMessage } from '../logics/runInteractionLogic'

export interface QueuedMessageListProps {
    messages: QueuedMessage[]
    onUpdate: (id: string, content: string) => void
    onRemove: (id: string) => void
    onSteer?: () => void
    steerPending?: boolean
    steerDisabledReason?: string
    /** The staged messages wait on the user, not on the agent — say so instead of looking like a queue. */
    held?: boolean
    /** Reports an open row editor, so the consumer can hold a send that would ship the pre-edit text. */
    onEditingChange?: (editing: boolean) => void
}

interface QueuedMessageItemProps {
    message: QueuedMessage
    isEditing: boolean
    onEdit: () => void
    onCancel: () => void
    onSave: (id: string, content: string) => void
    onRemove: (id: string) => void
}

/** One staged message — read row with edit/remove, or an inline editor. Logic-free (controlled). */
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
            <div className="space-y-2" data-attr="run-queue-editor">
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
        <div className="flex items-center gap-2 py-1 px-2 rounded-md border border-primary bg-surface-primary">
            <p className="flex-1 text-sm truncate mb-0">{message.content}</p>
            <div className="flex gap-0.5">
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
 * The editable queue rendered above the composer while the agent is busy. Purely presentational (no kea):
 * the consumer owns the queue state and passes `onUpdate` / `onRemove`. Modeled on PostHog AI's
 * `QueuedMessageItem`, minus the conversation/Max coupling.
 */
export function QueuedMessageList({
    messages,
    onUpdate,
    onRemove,
    onSteer,
    steerPending = false,
    steerDisabledReason,
    held = false,
    onEditingChange,
}: QueuedMessageListProps): JSX.Element | null {
    const [editingId, setEditingId] = useState<string | null>(null)
    const [collapsed, setCollapsed] = useState(false)
    // A row can leave while its editor is open — a flush clears the queue, and the consumer may drop a row
    // of its own. Holding a stale id would keep the send button disabled against an editor nobody can see.
    const editing = editingId !== null && messages.some((message) => message.id === editingId)

    useEffect(() => {
        onEditingChange?.(editing)
    }, [editing, onEditingChange])

    if (messages.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1 pb-2">
            <div className="flex flex-wrap items-center justify-between gap-1">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    data-attr="run-queue-toggle"
                    // Collapsing hides the editor, so close it first rather than leaving it open off screen.
                    onClick={() => {
                        setCollapsed(!collapsed)
                        setEditingId(null)
                    }}
                    icon={
                        <IconChevronDown
                            className={cn(
                                'transition-transform duration-150 ease-out motion-reduce:transition-none',
                                collapsed && '-rotate-90'
                            )}
                        />
                    }
                    tooltip={collapsed ? 'Show queued messages' : 'Hide queued messages'}
                >
                    <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
                        <IconStack />
                        <span data-attr="run-queue-label">
                            {messages.length} queued{held && ', not sent yet'}
                        </span>
                    </span>
                </LemonButton>
                {onSteer && (
                    <LemonButton
                        size="xsmall"
                        // The only way forward once the queue is held, so it carries the weight there.
                        type={held ? 'secondary' : 'tertiary'}
                        icon={<IconArrowRight />}
                        data-attr="run-queue-steer"
                        onClick={onSteer}
                        loading={steerPending}
                        disabledReason={steerDisabledReason ?? (editing ? 'Save or cancel your edit first' : undefined)}
                        tooltip="Sends without waiting for the agent to finish this turn."
                        sideIcon={<KeyboardShortcut escape />}
                    >
                        Send now
                    </LemonButton>
                )}
            </div>
            {/* Capped so a fast typist can't grow the banner until it pushes the composer off screen. */}
            {!collapsed && (
                <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
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
            )}
        </div>
    )
}
