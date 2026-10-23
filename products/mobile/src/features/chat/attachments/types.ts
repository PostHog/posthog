/** A file in the composer, not yet uploaded. It lives in memory only and never goes to the draft store. */
export interface PendingAttachment {
    /** Local key for the chip row. Two files can share a name. */
    id: string
    uri: string
    name: string
    size: number
    /** Derived from the extension, as the web does, because the sandbox reads the file by this type. */
    contentType: string
    isImage: boolean
    /** Web only: the picked file itself, so the upload reads it without fetching its `blob:` URL. */
    webFile?: Blob
}

export interface PickedFile {
    uri: string
    name: string
    /** Null when the platform did not report a size. */
    size: number | null
    webFile?: Blob
}

export type AttachmentSource = 'photos' | 'files'

export type AttachmentRejectionReason = 'empty' | 'too_large' | 'unreadable'
