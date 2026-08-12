export interface SkillFileUpload {
    path: string
    file: File
}

async function readAllDirectoryEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
    const entries: FileSystemEntry[] = []
    // readEntries returns results in batches (Chrome caps each call at 100 entries);
    // an empty batch signals the end of the directory.
    while (true) {
        const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
        if (batch.length === 0) {
            return entries
        }
        entries.push(...batch)
    }
}

async function collectEntry(entry: FileSystemEntry, uploads: SkillFileUpload[]): Promise<void> {
    if (entry.name.startsWith('.')) {
        return
    }
    // An unreadable entry (permissions, file vanished mid-drop) is skipped rather than
    // sinking everything collected so far.
    if (entry.isFile) {
        try {
            const file = await new Promise<File>((resolve, reject) =>
                (entry as FileSystemFileEntry).file(resolve, reject)
            )
            uploads.push({ path: entry.fullPath.replace(/^\//, ''), file })
        } catch {
            return
        }
        return
    }
    if (entry.isDirectory) {
        let children: FileSystemEntry[]
        try {
            children = await readAllDirectoryEntries((entry as FileSystemDirectoryEntry).createReader())
        } catch {
            return
        }
        for (const child of children) {
            await collectEntry(child, uploads)
        }
    }
}

/** Expand a drop into files, recursing into dropped folders. Must be called synchronously
 * from the drop event handler: DataTransferItems are unusable once the handler yields. */
export async function collectFilesFromDrop(dataTransfer: DataTransfer): Promise<SkillFileUpload[]> {
    const roots: (FileSystemEntry | File | null)[] = Array.from(dataTransfer.items ?? []).map(
        (item) => (typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null) ?? item.getAsFile()
    )
    if (roots.length === 0) {
        // Entry API entirely unavailable: fall back to the flat file list (no folder support)
        return Array.from(dataTransfer.files ?? [])
            .filter((file) => !file.name.startsWith('.'))
            .map((file) => ({ path: file.name, file }))
    }
    const uploads: SkillFileUpload[] = []
    for (const root of roots) {
        if (!root) {
            continue
        }
        if (root instanceof File) {
            if (!root.name.startsWith('.')) {
                uploads.push({ path: root.name, file: root })
            }
        } else {
            await collectEntry(root, uploads)
        }
    }
    return uploads
}
