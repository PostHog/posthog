import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconPlayFilled } from '@posthog/icons'

import type { NotebookComponentToolbarProps } from 'lib/components/MarkdownNotebook/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { notebookNodeGeneratedWidgetLogic } from './notebookNodeGeneratedWidgetLogic'
import { NotebookWidgetPublishModal } from './NotebookWidgetPublishModal'
import { DEFAULT_WIDGET_MODEL, isWidgetModel } from './widgetModels'

export function NotebookGeneratedWidgetRunButton({
    node,
    updateProps,
}: NotebookComponentToolbarProps): JSX.Element | null {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const mountedNodeLogic = useMountedLogic(notebookNodeLogic)
    const { canEditNotebook, isShared } = useValues(mountedNotebookLogic)

    if (isShared || !canEditNotebook) {
        return null
    }

    return (
        <EditableNotebookGeneratedWidgetRunButton
            node={node}
            mountedNodeLogic={mountedNodeLogic}
            updateProps={updateProps}
        />
    )
}

function EditableNotebookGeneratedWidgetRunButton({
    mountedNodeLogic,
    node,
    updateProps,
}: {
    mountedNodeLogic: ReturnType<typeof notebookNodeLogic.build>
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
    const { openPublishModal, runDataDependencies } = useActions(logic)
    const { setActions } = useActions(mountedNodeLogic)

    useEffect(() => {
        setActions([
            status?.is_reusable && status.widget_id
                ? {
                      text: 'Open reusable widget',
                      onClick: () => router.actions.push(urls.reusableWidget(status.widget_id!)),
                  }
                : status?.lifecycle_status === 'ready' && status.current_version_id
                  ? {
                        text: 'Convert to reusable widget',
                        onClick: openPublishModal,
                    }
                  : undefined,
        ])
    }, [
        openPublishModal,
        setActions,
        status?.current_version_id,
        status?.is_reusable,
        status?.lifecycle_status,
        status?.widget_id,
    ])

    useEffect(() => {
        if (!status) {
            return
        }
        if (!status.is_reusable) {
            if (node.props.id || node.props.version || node.props.inputs) {
                updateProps({ id: undefined, version: undefined, inputs: undefined })
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
        const version = status.pinned_version_id ?? undefined
        if (
            node.props.id !== status.widget_id ||
            node.props.version !== version ||
            JSON.stringify(node.props.inputs ?? {}) !== JSON.stringify(inputs)
        ) {
            updateProps({ id: status.widget_id, version, inputs })
        }
    }, [node.props.id, node.props.inputs, node.props.version, status, updateProps])

    return (
        <>
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
            <NotebookWidgetPublishModal {...logicProps} />
        </>
    )
}
