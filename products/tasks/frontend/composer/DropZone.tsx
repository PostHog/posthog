import { DragEvent, JSX, ReactNode, useCallback, useRef, useState } from 'react'

import { IconUpload } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

interface DropZoneProps {
    children: ReactNode
    onDropFiles: (files: File[]) => void
    className?: string
}

/** Wraps an area so files can be dragged onto it; shows a full-area overlay while dragging. */
export function DropZone({ children, onDropFiles, className }: DropZoneProps): JSX.Element {
    const [isDraggingFile, setIsDraggingFile] = useState(false)
    // Counter instead of boolean: dragenter/dragleave fire for every nested child,
    // so a single boolean would flicker off as the cursor crosses children.
    const dragCounterRef = useRef(0)

    const handleDragEnter = useCallback((e: DragEvent<HTMLDivElement>): void => {
        e.preventDefault()
        e.stopPropagation()
        dragCounterRef.current += 1
        if (e.dataTransfer?.types.includes('Files')) {
            setIsDraggingFile(true)
        }
    }, [])

    const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>): void => {
        e.preventDefault()
        e.stopPropagation()
        dragCounterRef.current = Math.max(0, dragCounterRef.current - 1)
        if (dragCounterRef.current === 0) {
            setIsDraggingFile(false)
        }
    }, [])

    const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>): void => {
        e.preventDefault()
        e.stopPropagation()
    }, [])

    const handleDrop = useCallback(
        (e: DragEvent<HTMLDivElement>): void => {
            e.preventDefault()
            e.stopPropagation()
            dragCounterRef.current = 0
            setIsDraggingFile(false)

            // Drops on the editor are handled by the editor itself — don't double-attach.
            if ((e.target as HTMLElement).closest('.LemonTextArea')) {
                return
            }

            const files = Array.from(e.dataTransfer?.files ?? [])
            if (files.length === 0) {
                return
            }
            onDropFiles(files)
        },
        [onDropFiles]
    )

    return (
        <div
            className={cn('relative', className)}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            data-attr="task-drop-zone"
        >
            {children}
            {isDraggingFile && (
                <div
                    className="pointer-events-none absolute inset-0 z-50 m-1 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-bg-light opacity-90"
                    data-attr="task-drop-zone-overlay"
                >
                    <div className="flex flex-col items-center gap-2 text-accent">
                        <IconUpload className="text-2xl" />
                        <span className="text-sm font-medium">Drop files to attach</span>
                    </div>
                </div>
            )}
        </div>
    )
}
