import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import type { MessageTemplate } from './types'

// A soft delete removes the template's file entry, and the template keeps no record of its folder. The
// undo therefore restores through the project tree with the path read before the delete, so that the
// template returns to its folder and not to the default folder.
export async function deleteTemplateWithUndo({
    teamId,
    template,
    callback,
}: {
    teamId: number | string
    template: Pick<MessageTemplate, 'id' | 'name'>
    callback: (undo: boolean) => void
}): Promise<void> {
    const path = await filePathOf(template.id)
    await deleteWithUndo({
        endpoint: `environments/${teamId}/messaging_templates`,
        object: { id: template.id, name: template.name },
        restore: () => api.fileSystem.undoDelete([{ type: 'message_template', ref: template.id, path }]),
        callback,
    })
}

async function filePathOf(templateId: string): Promise<string | undefined> {
    const loaded = projectTreeDataLogic.findMounted()?.values.itemsByRef[`message_template::${templateId}`]
    if (loaded) {
        return loaded.path
    }
    try {
        const entries = await api.fileSystem.list({ type: 'message_template', ref: templateId })
        return entries.results.find((entry) => !entry.shortcut)?.path
    } catch {
        return undefined
    }
}
