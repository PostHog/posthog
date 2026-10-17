import { ApiError, apiJson, projectPath } from './client'
import type { PaginatedApi } from './reports'

// Shapes follow `FileSystemShortcutSerializer` in `posthog/api/file_system/file_system_shortcut.py`. These rows are the
// web's "Starred" items: the app uses the default surface, so a pin made here shows as a star on the web.

export interface FileSystemShortcutApi {
    id: string
    /** Escaped like the web's `joinPath`: `/` as `\/` and `\` as `\\`. */
    path: string
    type: string | null
    ref: string | null
    href: string | null
    order: number | null
    created_at: string
}

/** What `POST file_system_shortcut/` takes. The server returns the existing row on an exact match. */
export interface ShortcutInput {
    path: string
    type: string
    ref: string | null
    href: string
}

/** One page holds every pin the app shows. A longer list shows a note instead of a second page. */
export const SHORTCUT_PAGE_SIZE = 100

export function fetchShortcuts(signal?: AbortSignal): Promise<PaginatedApi<FileSystemShortcutApi>> {
    return apiJson<PaginatedApi<FileSystemShortcutApi>>(projectPath('file_system_shortcut/'), {
        query: { limit: SHORTCUT_PAGE_SIZE },
        signal,
    })
}

export function createShortcut(input: ShortcutInput): Promise<FileSystemShortcutApi> {
    return apiJson<FileSystemShortcutApi>(projectPath('file_system_shortcut/'), { method: 'POST', json: input })
}

/** Works for a row in any environment of the project. A 404 means the row is already gone, which is the goal. */
export async function deleteShortcut(id: string): Promise<void> {
    try {
        await apiJson<unknown>(projectPath(`file_system_shortcut/${encodeURIComponent(id)}/`), { method: 'DELETE' })
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            return
        }
        throw error
    }
}
