import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlayFilled } from '@posthog/icons'

import type { NotebookComponentToolbarProps } from 'lib/components/MarkdownNotebook/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { teamLogic } from 'scenes/teamLogic'

import { notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { DEFAULT_WIDGET_MODEL, isWidgetModel } from './widgetModels'

export function NotebookGeneratedWidgetRunButton({
    node,
    notebookMode,
    updateProps,
}: NotebookComponentToolbarProps): JSX.Element | null {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { canEditNotebook, isShared } = useValues(mountedNotebookLogic)
    const isEditableNotebook = !isShared && canEditNotebook && notebookMode === 'edit'
    // Props the parser could not read, and a paired tag's body, exist only in the block's raw
    // source, which any prop write clears. An automatic write must not shorten a block that no
    // person edited, so those blocks keep their derived id instead.
    const hasSourceOnlyInRaw = !!node.errors?.length || !!node.raw?.includes('\n')

    // A parsed block id is a hash of the block's props, so any prop write moves it (a resize
    // writes `height`, editing the prompt or the title writes those). The widget's generation
    // state lives on the server under the block id, so a block that carries no explicit id gets
    // one the first time it renders for an editor. The write belongs in the toolbar because the
    // shell mounts the toolbar for every block, while it mounts the results panel only when that
    // panel is open. It stays out of the undo history, which the person owns.
    useEffect(() => {
        if (!isEditableNotebook || hasSourceOnlyInRaw) {
            return
        }
        if (typeof node.props.nodeId !== 'string' || !node.props.nodeId) {
            updateProps({ nodeId: node.id }, { addToHistory: false })
        }
    }, [hasSourceOnlyInRaw, isEditableNotebook, node.id, node.props.nodeId, updateProps])

    if (isShared || !canEditNotebook) {
        return null
    }

    return <EditableNotebookGeneratedWidgetRunButton node={node} />
}

function EditableNotebookGeneratedWidgetRunButton({
    node,
}: {
    node: NotebookComponentToolbarProps['node']
}): JSX.Element {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { canEditNotebook } = useValues(mountedNotebookLogic)
    const { currentTeamId } = useValues(teamLogic)
    const nodeId = typeof node.props.nodeId === 'string' && node.props.nodeId ? node.props.nodeId : node.id
    const model =
        typeof node.props.model === 'string' && isWidgetModel(node.props.model)
            ? node.props.model
            : DEFAULT_WIDGET_MODEL
    const logic = notebookNodeGeneratedWidgetLogic({
        projectId: currentTeamId,
        notebookShortId: mountedNotebookLogic.props.shortId,
        nodeId,
        prompt: typeof node.props.prompt === 'string' ? node.props.prompt : '',
        model,
        isEditable: canEditNotebook,
        persistNotebook: async (): Promise<void> => {
            await mountedNotebookLogic.asyncActions.saveNotebook({
                content: mountedNotebookLogic.values.content,
                title: mountedNotebookLogic.values.title,
            })
        },
        getContent: () => mountedNotebookLogic.values.content ?? null,
    })
    const { dataRefreshInFlight, runDataDependenciesDisabledReason } = useValues(logic)
    const { runDataDependencies } = useActions(logic)

    return (
        <LemonButton
            data-attr="notebook-generated-widget-run-button"
            size="xsmall"
            type="primary"
            icon={<IconPlayFilled color="var(--success)" />}
            onClick={runDataDependencies}
            loading={dataRefreshInFlight}
            disabledReason={runDataDependenciesDisabledReason ?? undefined}
            tooltip="Run widget data cells"
        >
            Run
        </LemonButton>
    )
}
