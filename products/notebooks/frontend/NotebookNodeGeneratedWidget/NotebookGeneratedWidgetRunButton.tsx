import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPlayFilled } from '@posthog/icons'

import type { NotebookComponentToolbarProps } from 'lib/components/MarkdownNotebook/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { DEFAULT_WIDGET_MODEL, isWidgetModel } from './widgetModels'

export function NotebookGeneratedWidgetRunButton({ node }: NotebookComponentToolbarProps): JSX.Element | null {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { canEditNotebook, isShared } = useValues(mountedNotebookLogic)
    const nodeId = typeof node.props.nodeId === 'string' && node.props.nodeId ? node.props.nodeId : node.id
    const isEditable = canEditNotebook && !isShared
    const logic = notebookNodeGeneratedWidgetLogic({
        notebookShortId: mountedNotebookLogic.props.shortId,
        nodeId,
        prompt: typeof node.props.prompt === 'string' ? node.props.prompt : '',
        model:
            typeof node.props.model === 'string' && isWidgetModel(node.props.model)
                ? node.props.model
                : DEFAULT_WIDGET_MODEL,
        isEditable,
        persistNotebook: async (): Promise<void> => {
            await mountedNotebookLogic.asyncActions.saveNotebook({
                content: mountedNotebookLogic.values.content,
                title: mountedNotebookLogic.values.title,
            })
        },
    })
    const { dataRunInFlight, isCellChainRunning, isNotebookBusy, isWorking, status } = useValues(logic)
    const { runWidget } = useActions(logic)

    if (!isEditable || !status?.has_versions) {
        return null
    }

    const disabledReason = isWorking
        ? 'Wait for widget generation to finish'
        : isCellChainRunning
          ? 'Wait for the running cells to finish'
          : isNotebookBusy
            ? 'Wait for the current notebook operation to finish'
            : undefined

    return (
        <LemonButton
            data-attr="notebook-generated-widget-run-button"
            size="xsmall"
            type="primary"
            icon={<IconPlayFilled color="var(--success)" />}
            onClick={runWidget}
            loading={dataRunInFlight}
            disabledReason={disabledReason}
            tooltip="Run widget"
        >
            Run
        </LemonButton>
    )
}
