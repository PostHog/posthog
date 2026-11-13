import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { messagingTemplatesPlacementRetrieve } from 'products/messaging/frontend/generated/api'

import type { MessageTemplate } from './types'

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
    let filePathTheUndoRestores: string | undefined
    try {
        filePathTheUndoRestores = await storedFilePathOf(teamId, template.id)
    } catch {
        keepTheTemplateAndOfferRetry(retry)
        return false
    }
    await deleteWithUndo({
        endpoint: `environments/${teamId}/messaging_templates`,
        object: { id: template.id, name: template.name },
        restore: () =>
            api.fileSystem.undoDelete([{ type: 'message_template', ref: template.id, path: filePathTheUndoRestores }]),
        callback,
    })
    return true
}

async function storedFilePathOf(teamId: number | string, templateId: string): Promise<string | undefined> {
    const { path } = await messagingTemplatesPlacementRetrieve(String(teamId), templateId)
    return path ?? undefined
}

function keepTheTemplateAndOfferRetry(retry: () => void): void {
    lemonToast.error("Couldn't delete the template. Retry, and if it keeps happening contact support.", {
        button: { label: 'Retry', action: retry },
    })
}
