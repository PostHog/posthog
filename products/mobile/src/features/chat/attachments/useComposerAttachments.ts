import { randomUUID } from 'expo-crypto'
import { useCallback, useRef, useState } from 'react'
import { Platform } from 'react-native'

import { track } from '@/lib/analytics'

import { addPickedFiles, MAX_ATTACHMENTS_PER_MESSAGE, pickNotice } from './attachmentRules'
import { pickFiles, pickPhotos } from './pickAttachments'
import type { AttachmentSource, PendingAttachment, PickedFile } from './types'

const PICKER_FAILED: Record<AttachmentSource, string> = {
    photos: "Couldn't open your photos. Try again.",
    files: "Couldn't open your files. Try again.",
}

/** A web pick holds its preview as a `blob:` URL, which stays in memory until it is revoked. */
export function releaseAttachments(files: readonly PendingAttachment[]): void {
    if (Platform.OS !== 'web' || typeof URL.revokeObjectURL !== 'function') {
        return
    }
    for (const file of files) {
        if (file.uri.startsWith('blob:')) {
            URL.revokeObjectURL(file.uri)
        }
    }
}

export interface ComposerAttachments {
    files: readonly PendingAttachment[]
    notice: string | undefined
    isFull: boolean
    pick: (source: AttachmentSource) => Promise<void>
    remove: (id: string) => void
    /**
     * Drops the files, or only those in `only`. `release: false` keeps web previews alive for a sent file, whose
     * bubble still shows them.
     */
    clear: (options?: { only?: readonly string[]; release?: boolean }) => void
    dismissNotice: () => void
}

/** The composer's picked files. They stay in memory, so a closed chat or an app restart drops them. */
export function useComposerAttachments(): ComposerAttachments {
    const [files, setFilesState] = useState<readonly PendingAttachment[]>([])
    const latest = useRef(files)
    const [notice, setNotice] = useState<string | undefined>(undefined)

    const setFiles = useCallback((next: readonly PendingAttachment[]): void => {
        latest.current = next
        setFilesState(next)
    }, [])

    const pick = useCallback(
        async (source: AttachmentSource): Promise<void> => {
            let picked: PickedFile[]
            try {
                const slots = Math.max(1, MAX_ATTACHMENTS_PER_MESSAGE - latest.current.length)
                picked = source === 'photos' ? await pickPhotos(slots) : await pickFiles()
            } catch {
                setNotice(PICKER_FAILED[source])
                return
            }
            if (picked.length === 0) {
                return
            }
            const result = addPickedFiles(latest.current, picked, randomUUID)
            for (const rejection of result.rejected) {
                track('mobile_chat_file_rejected', { reason: rejection.reason })
            }
            if (result.leftOff > 0) {
                track('mobile_chat_file_rejected', { reason: 'too_many' })
            }
            if (result.added.length > 0) {
                const next = [...latest.current, ...result.added]
                setFiles(next)
                track('mobile_chat_file_attached', {
                    source,
                    attached_count: next.length,
                    image_count: result.added.filter((file) => file.isImage).length,
                })
            }
            setNotice(pickNotice(result))
        },
        [setFiles]
    )

    const remove = useCallback(
        (id: string): void => {
            releaseAttachments(latest.current.filter((file) => file.id === id))
            const next = latest.current.filter((file) => file.id !== id)
            setFiles(next)
            track('mobile_chat_file_removed', { attached_count: next.length })
        },
        [setFiles]
    )

    const clear = useCallback(
        ({ only, release = true }: { only?: readonly string[]; release?: boolean } = {}): void => {
            const dropped = only ? latest.current.filter((file) => only.includes(file.id)) : latest.current
            if (release) {
                releaseAttachments(dropped)
            }
            setFiles(latest.current.filter((file) => !dropped.includes(file)))
            setNotice(undefined)
        },
        [setFiles]
    )

    const dismissNotice = useCallback((): void => setNotice(undefined), [])

    return {
        files,
        notice,
        isFull: files.length >= MAX_ATTACHMENTS_PER_MESSAGE,
        pick,
        remove,
        clear,
        dismissNotice,
    }
}
