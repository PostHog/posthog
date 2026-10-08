import { type RefObject, useEffect, useRef, useState } from 'react'

/**
 * Not `LemonFileInput`'s `alternativeDropTargetRef`: it keeps its own copy of the file list and re-syncs it
 * only when the `value` prop changes identity, so a composer whose logic owns the list grows that copy and
 * re-reports every earlier file on each drop.
 */
export function useFileDrop(target: RefObject<HTMLElement> | undefined, onFiles: (files: File[]) => void): boolean {
    const [isOver, setIsOver] = useState(false)
    // Dragging over a child fires dragleave on the parent, so count nesting rather than flicker off.
    const depth = useRef(0)
    const onFilesRef = useRef(onFiles)
    onFilesRef.current = onFiles

    useEffect(() => {
        const node = target?.current
        if (!node) {
            return
        }
        const carriesFiles = (event: DragEvent): boolean =>
            Array.from(event.dataTransfer?.types ?? []).includes('Files')
        const onDragEnter = (event: DragEvent): void => {
            if (!carriesFiles(event)) {
                return
            }
            depth.current += 1
            setIsOver(true)
        }
        const onDragOver = (event: DragEvent): void => {
            if (carriesFiles(event)) {
                // Or the browser takes the drop itself and navigates to the file.
                event.preventDefault()
            }
        }
        const onDragLeave = (): void => {
            depth.current = Math.max(0, depth.current - 1)
            if (depth.current === 0) {
                setIsOver(false)
            }
        }
        const onDrop = (event: DragEvent): void => {
            if (!carriesFiles(event)) {
                return
            }
            event.preventDefault()
            depth.current = 0
            setIsOver(false)
            const files = Array.from(event.dataTransfer?.files ?? [])
            if (files.length > 0) {
                onFilesRef.current(files)
            }
        }

        node.addEventListener('dragenter', onDragEnter)
        node.addEventListener('dragover', onDragOver)
        node.addEventListener('dragleave', onDragLeave)
        node.addEventListener('drop', onDrop)
        return () => {
            node.removeEventListener('dragenter', onDragEnter)
            node.removeEventListener('dragover', onDragOver)
            node.removeEventListener('dragleave', onDragLeave)
            node.removeEventListener('drop', onDrop)
        }
    }, [target])

    return isOver
}
