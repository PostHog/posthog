import { router } from 'kea-router'

import { IconPencil } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { replayVisionFeedbackAction } from '../components/replayVisionFeedbackAction'

const RESOURCE_TYPE = 'replay-scanner'

interface ReplayScannerSceneMenuBarProps {
    editUrl: string
    editDisabledReason: string | null
    scannerType: string
}

export function ReplayScannerSceneMenuBar(props: ReplayScannerSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ReplayScannerSceneMenuBarInner {...props} /> : null
}

function ReplayScannerSceneMenuBarInner({
    editUrl,
    editDisabledReason,
    scannerType,
}: ReplayScannerSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-edit`,
            label: 'Edit scanner',
            icon: <IconPencil />,
            disabledReason: editDisabledReason ?? undefined,
            onSelect: () => router.actions.push(editUrl),
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <Button
                        variant="primary"
                        render={<LinkPrimitive to={editDisabledReason ? undefined : editUrl} />}
                        disabledReason={editDisabledReason}
                        data-attr="vision-scanner-edit"
                        data-ph-capture-attribute-scanner-type={scannerType}
                    >
                        Edit scanner
                    </Button>
                ),
            },
        },
        replayVisionFeedbackAction(RESOURCE_TYPE, { order: 1, variant: 'secondary' }),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
