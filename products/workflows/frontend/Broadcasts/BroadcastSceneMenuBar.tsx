import { useActions, useValues } from 'kea'

import { IconArchive, IconCopy, IconPencil, IconTrash, IconUndo } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { manageDisabledReason, summaryActions } from './broadcastLifecycle'
import { broadcastWizardLogic } from './broadcastWizardLogic'

const RESOURCE_TYPE = 'broadcast'
const SAVING_REASON = 'Wait for the broadcast to finish saving'

interface BroadcastSceneMenuBarProps {
    /** The wizard edits a draft; the summary shows a launched or archived broadcast. */
    mode: 'wizard' | 'summary'
    /** The header's own actions control, kept as the title row control. */
    titleActions?: JSX.Element
}

export function BroadcastSceneMenuBar(props: BroadcastSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <BroadcastSceneMenuBarInner {...props} /> : null
}

const SUMMARY_ROWS: Record<string, Pick<SceneAction, 'group' | 'section' | 'icon'>> = {
    'broadcast-move-to-draft': { group: 'edit', section: 'state', icon: <IconPencil /> },
    'broadcast-send-again': { group: 'edit', icon: <IconCopy /> },
    'broadcast-restore': { group: 'file', section: 'delete', icon: <IconUndo /> },
    'broadcast-archive': { group: 'file', section: 'delete', icon: <IconArchive /> },
    'broadcast-delete': { group: 'file', section: 'delete', icon: <IconTrash /> },
}

function BroadcastSceneMenuBarInner({ mode, titleActions }: BroadcastSceneMenuBarProps): JSX.Element {
    const {
        broadcast,
        broadcastId,
        saving,
        launching,
        batchJobs,
        hasLoadedBatchJobs,
        canMoveToDraft,
        canEditContent,
        movingToDraft,
        duplicating,
    } = useValues(broadcastWizardLogic)
    const {
        openInWorkflowEditor,
        archiveBroadcast,
        moveToDraft,
        duplicateBroadcast,
        restoreBroadcast,
        deleteBroadcast,
    } = useActions(broadcastWizardLogic)

    const confirmMoveToDraft = (): void => {
        const pendingSchedule = broadcast?.schedules?.find((schedule) => schedule.status === 'active')
        LemonDialog.open({
            title: pendingSchedule ? 'Stop this broadcast and edit it?' : 'Move this broadcast to draft?',
            description: pendingSchedule
                ? 'The scheduled send stops and the broadcast goes back to draft. Nothing sends until you launch it again.'
                : 'The broadcast goes back to draft, so you can check it and launch it again.',
            primaryButton: {
                children: 'Stop and edit',
                onClick: moveToDraft,
                'data-attr': 'broadcast-move-to-draft-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const pinTitleActions = (order: number): SceneAction['pinned'] =>
        titleActions
            ? { order, variant: 'secondary', dataAttr: 'broadcast-actions', render: () => titleActions }
            : undefined

    let actions: SceneAction[] = []
    if (mode === 'wizard' && broadcastId) {
        const busyReason = saving || launching ? SAVING_REASON : undefined
        actions = [
            {
                group: 'view',
                // pinned: data-attr values are wire strings
                id: 'broadcast-open-in-workflow-editor',
                label: 'Open in workflow editor',
                disabledReason: busyReason,
                onSelect: openInWorkflowEditor,
                pinned: pinTitleActions(1),
            },
            {
                group: 'file',
                section: 'delete',
                id: 'broadcast-archive',
                label: 'Archive',
                icon: <IconArchive />,
                destructive: true,
                disabledReason: manageDisabledReason(broadcast?.user_access_level) ?? busyReason,
                onSelect: archiveBroadcast,
            },
        ]
    } else if (mode === 'summary') {
        const busyReason = movingToDraft || duplicating ? SAVING_REASON : undefined
        actions = summaryActions({
            userAccessLevel: broadcast?.user_access_level,
            canMoveToDraft,
            canEditContent,
            isArchived: broadcast?.status === 'archived',
            batchJobStatuses: hasLoadedBatchJobs ? batchJobs.map((job) => job.status) : null,
            onMoveToDraft: confirmMoveToDraft,
            onSendAgain: duplicateBroadcast,
            onRestore: restoreBroadcast,
            onArchive: archiveBroadcast,
            onDelete: deleteBroadcast,
        }).map(
            (item, index): SceneAction => ({
                ...SUMMARY_ROWS[item['data-attr']],
                id: item['data-attr'],
                label: item.label,
                destructive: item.status === 'danger' || item['data-attr'] === 'broadcast-restore',
                disabledReason: item.disabledReason ?? busyReason,
                onSelect: item.onClick,
                pinned: index === 0 ? pinTitleActions(1) : undefined,
            })
        )
    }

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
