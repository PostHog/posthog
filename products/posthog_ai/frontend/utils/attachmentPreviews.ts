/**
 * Holds the `File` a send staged, so its message can draw the real image while the upload is in flight.
 *
 * Keyed by an id the echo carries, since a name is not unique across messages. An entry only matters until
 * the artifact exists — a reload finds an empty registry and falls back to the artifact — so the oldest are
 * dropped rather than held for the life of the tab.
 */

const MAX_TRACKED_PREVIEWS = 20

const previews = new Map<string, File>()
let sequence = 0

export function rememberAttachmentPreview(file: File): string {
    const id = `preview-${++sequence}`
    previews.set(id, file)
    while (previews.size > MAX_TRACKED_PREVIEWS) {
        const oldest = previews.keys().next()
        if (oldest.done) {
            break
        }
        previews.delete(oldest.value)
    }
    return id
}

export function getAttachmentPreview(previewId: string | undefined): File | undefined {
    return previewId ? previews.get(previewId) : undefined
}

/** Test seam: module state would otherwise leak between cases. */
export function clearAttachmentPreviews(): void {
    previews.clear()
    sequence = 0
}
