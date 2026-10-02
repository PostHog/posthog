import { type ReactNode, useState } from 'react'

import { IconChevronLeft, IconPencil } from '@posthog/icons'
import { Button, Heading, Input, SkeletonText } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillTaskTitleProps {
    name: string
    icon: ReactNode
    isLoading: boolean
    /** Omitting this leaves the title read-only. */
    onRename?: (title: string) => void
    backTo?: { label: string; path: string }
    actions?: ReactNode
}

export function QuillTaskTitle({ name, icon, isLoading, onRename, backTo, actions }: QuillTaskTitleProps): JSX.Element {
    const [draft, setDraft] = useState<string | null>(null)

    const commit = (): void => {
        if (draft !== null) {
            onRename?.(draft)
        }
        setDraft(null)
    }

    return (
        <div data-quill className="flex flex-wrap items-center gap-2 py-2">
            {backTo && (
                <Button
                    variant="default"
                    size="icon-sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={backTo.path} />}
                    aria-label={`Back to ${backTo.label}`}
                >
                    <IconChevronLeft />
                </Button>
            )}
            <span className="flex size-5 shrink-0 items-center justify-center text-sm" aria-hidden>
                {icon}
            </span>
            <div className="flex min-w-0 flex-1 items-center gap-1">
                {isLoading ? (
                    <SkeletonText lines={1} className="w-60" />
                ) : draft !== null ? (
                    <Input
                        aria-label="Task title"
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        onBlur={commit}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault()
                                commit()
                            } else if (event.key === 'Escape') {
                                event.preventDefault()
                                setDraft(null)
                            }
                        }}
                        autoFocus
                        // Same height as the pencil button, and pulled left by its padding and border, so the text stays put on edit.
                        className="-ms-[calc(0.5rem+1px)] h-6 max-w-120 text-sm font-semibold"
                    />
                ) : (
                    <>
                        <Heading size="sm" render={<h1 />} className="m-0 min-w-0 truncate">
                            {name}
                        </Heading>
                        {onRename && (
                            <Button
                                variant="default"
                                size="icon-sm"
                                aria-label="Rename task"
                                onClick={() => setDraft(name)}
                                data-attr="task-rename"
                            >
                                <IconPencil />
                            </Button>
                        )}
                    </>
                )}
            </div>
            {actions && <div className="ml-auto flex flex-wrap items-center gap-1">{actions}</div>}
        </div>
    )
}
