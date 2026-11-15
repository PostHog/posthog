import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Text } from '@posthog/quill-primitives'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { EDITOR_LANGUAGE } from '../taskRunArtifacts'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'
import { ArtifactSaveConflictDialog } from './ArtifactSaveConflictDialog'

/** The source of the file under edit. The logic holds the draft, so a remount in full page keeps it. */
export function ArtifactEditor({ taskId }: { taskId: string }): JSX.Element | null {
    const { editSession, editDraft, editError } = useValues(taskRunArtifactsLogic({ taskId }))
    const { setEditDraft } = useActions(taskRunArtifactsLogic({ taskId }))
    if (!editSession) {
        return null
    }
    return (
        <div className="flex min-h-0 flex-1 flex-col">
            {editError && (
                <div
                    role="alert"
                    className="flex shrink-0 items-center gap-2 border-b border-border bg-destructive px-3 py-2 text-destructive-foreground"
                >
                    <IconWarning className="size-4 shrink-0" />
                    <Text size="xs" render={<span />} className="min-w-0 text-destructive-foreground">
                        {editError}
                    </Text>
                </div>
            )}
            <div className="min-h-0 flex-1 bg-background" data-attr="task-artifact-editor">
                <CodeEditor
                    queryKey={`task-artifact-edit-${editSession.baseArtifactId}`}
                    language={EDITOR_LANGUAGE[editSession.kind]}
                    value={editDraft}
                    onChange={(value) => setEditDraft(value ?? '')}
                    autoFocus
                    options={{ wordWrap: 'on' }}
                />
            </div>
            <ArtifactSaveConflictDialog taskId={taskId} />
        </div>
    )
}
