import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPlayFilled } from '@posthog/icons'

import { usePublishNotebookComponentRunHandler } from 'lib/components/MarkdownNotebook/componentRunHandlers'
import type { NotebookComponentToolbarProps } from 'lib/components/MarkdownNotebook/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { teamLogic } from 'scenes/teamLogic'

import { notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { DEFAULT_WIDGET_MODEL, isWidgetModel } from './widgetModels'

export function NotebookGeneratedWidgetRunButton({ node }: NotebookComponentToolbarProps): JSX.Element | null {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { canEditNotebook, isShared } = useValues(mountedNotebookLogic)

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

    // A refresh in flight blocks the shortcuts, matching the button, which is disabled while it loads.
    usePublishNotebookComponentRunHandler({
        run: runDataDependencies,
        disabledReason: dataRefreshInFlight
            ? 'This widget is already running'
            : (runDataDependenciesDisabledReason ?? null),
    })

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
