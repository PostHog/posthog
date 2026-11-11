import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import type { MessageTemplate } from './types'

// A soft delete removes the template's file entry, and the template keeps no record of its folder. The
// undo therefore restores through the project tree with the path read before the delete, so that the
// template returns to its folder and not to the default folder. When the path cannot be read, the template
// stays, because a delete then would make the undo lose its folder, and the error offers `retry`. Returns
// whether the delete went ahead.
export async function deleteTemplateWithUndo({
    teamId,
    template,
    callback,
    retry,
}: {
    teamId: number | string
    template: Pick<MessageTemplate, 'id' | 'name'>
    callback: (undo: boolean) => void
    retry: () => void
}): Promise<boolean> {
    let path: string | undefined
    try {
        path = await filePathOf(template.id)
    } catch {
        lemonToast.error("Couldn't delete the template. Retry, and if it keeps happening contact support.", {
            button: { label: 'Retry', action: retry },
        })
        return false
    }
    await deleteWithUndo({
        endpoint: `environments/${teamId}/messaging_templates`,
        object: { id: template.id, name: template.name },
        restore: () => api.fileSystem.undoDelete([{ type: 'message_template', ref: template.id, path }]),
        callback,
    })
    return true
}

async function filePathOf(templateId: string): Promise<string | undefined> {
    const loaded = projectTreeDataLogic.findMounted()?.values.itemsByRef[`message_template::${templateId}`]
    if (loaded) {
        return loaded.path
    }
    const entries = await api.fileSystem.list({ type: 'message_template', ref: templateId })
    return entries.results.find((entry) => !entry.shortcut)?.path
}
