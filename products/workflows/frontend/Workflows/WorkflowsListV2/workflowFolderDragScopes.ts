export const WORKFLOW_FILES_DRAG_SCOPE = 'workflow-project-files'

// The sidebar, the folder view and the breadcrumbs can show the same folder at once. Each surface gets its own
// scope so their drop target ids stay distinct, because dnd-kit keeps only one droppable per id.
export const WORKFLOW_FOLDER_CONTENTS_DROP_SCOPE = 'workflow-folder-contents'
export const WORKFLOW_FOLDER_BREADCRUMBS_DROP_SCOPE = 'workflow-folder-breadcrumbs'

export const WORKFLOW_FOLDER_DROP_SCOPES = [
    WORKFLOW_FILES_DRAG_SCOPE,
    WORKFLOW_FOLDER_CONTENTS_DROP_SCOPE,
    WORKFLOW_FOLDER_BREADCRUMBS_DROP_SCOPE,
]
