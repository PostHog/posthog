import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPlayFilled } from '@posthog/icons'

import type { NotebookComponentToolbarProps } from 'lib/components/MarkdownNotebook/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { teamLogic } from 'scenes/teamLogic'

import { notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { NotebookWidgetPublishModal } from './NotebookWidgetPublishModal'
import { NotebookWidgetSourceModal } from './NotebookWidgetSourceModal'
import { DEFAULT_WIDGET_MODEL, isWidgetModel } from './widgetModels'

export function NotebookGeneratedWidgetRunButton({
    node,
    updateProps,
}: NotebookComponentToolbarProps): JSX.Element | null {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { isShared } = useValues(mountedNotebookLogic)

    if (isShared) {
        return null
    }

    return <EditableNotebookGeneratedWidgetRunButton node={node} updateProps={updateProps} />
}

function EditableNotebookGeneratedWidgetRunButton({
    node,
    updateProps,
}: {
    node: NotebookComponentToolbarProps['node']
    updateProps: NotebookComponentToolbarProps['updateProps']
}): JSX.Element {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { canEditNotebook } = useValues(mountedNotebookLogic)
    const { currentTeamId } = useValues(teamLogic)
    const nodeId = typeof node.props.nodeId === 'string' && node.props.nodeId ? node.props.nodeId : node.id
    const model =
        typeof node.props.model === 'string' && isWidgetModel(node.props.model)
            ? node.props.model
            : DEFAULT_WIDGET_MODEL
    const logicProps = {
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
    }
    const logic = notebookNodeGeneratedWidgetLogic(logicProps)
    const { dataRefreshInFlight, runDataDependenciesDisabledReason, status } = useValues(logic)
    const { runDataDependencies } = useActions(logic)

    useEffect(() => {
        if (!canEditNotebook || !status?.instance_id || !status.has_versions) {
            return
        }
        const version = status.pinned_version_id ?? undefined
        if (!status.is_reusable) {
            if (node.props.id || node.props.version !== version) {
                updateProps({
                    nodeId,
                    id: undefined,
                    version,
                    ...(node.props.id ? { inputs: undefined } : {}),
                })
            }
            return
        }
        if (!status.widget_id) {
            return
        }
        const inputs = Object.fromEntries(
            Object.entries(status.input_bindings).map(([slot, binding]) => [
                slot,
                { source: binding.source, ...(binding.hog ? { hog: binding.hog } : {}) },
            ])
        )
        if (
            node.props.id !== status.widget_id ||
            node.props.version !== version ||
            JSON.stringify(node.props.inputs ?? {}) !== JSON.stringify(inputs)
        ) {
            updateProps({ nodeId, id: status.widget_id, version, inputs })
        }
    }, [canEditNotebook, nodeId, node.props.id, node.props.inputs, node.props.version, status, updateProps])

    return (
        <>
            {canEditNotebook ? (
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
            ) : null}
            {canEditNotebook ? <NotebookWidgetPublishModal {...logicProps} /> : null}
            <NotebookWidgetSourceModal {...logicProps} />
        </>
    )
}
