import { FileSystemEntry } from '~/queries/schema/schema-general'

/** Each object's file keyed `type::ref`. A shortcut stands in only while the object's own file isn't loaded. */
export function workflowFilesByRef(items: FileSystemEntry[]): Record<string, FileSystemEntry> {
    const filesByRef: Record<string, FileSystemEntry> = {}
    for (const item of items) {
        const key = `${item.type}::${item.ref}`
        if (item.type && item.ref && (!item.shortcut || !filesByRef[key])) {
            filesByRef[key] = item
        }
    }
    return filesByRef
}
