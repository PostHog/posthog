import { router } from 'kea-router'

const FOLDER_PARAM = '_create_in_folder'

// The router reads a number-like value such as `007` back as a number on every later navigation, so the folder
// travels with a trailing slash, which no number has.
export function newWorkflowFolderParam(folder: string | null | undefined): Record<string, string> {
    return folder && folder !== 'Unfiled' ? { [FOLDER_PARAM]: `${folder}/` } : {}
}

/** The project folder a new workflow is created in, as carried in the address. */
export function newWorkflowFolder(search: string = router.values.location.search): string | null {
    return new URLSearchParams(search).get(FOLDER_PARAM)?.replace(/\/$/, '') || null
}
