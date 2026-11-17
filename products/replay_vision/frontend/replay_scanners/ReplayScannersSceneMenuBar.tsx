import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { replayVisionFeedbackAction } from '../components/replayVisionFeedbackAction'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { QuillCreateScannerButton } from './components/QuillCreateScannerButton'

const RESOURCE_TYPE = 'replay-scanners'

export function ReplayScannersSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ReplayScannersSceneMenuBarInner /> : null
}

function ReplayScannersSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-scanner`,
            label: 'New scanner',
            icon: <IconPlusSmall />,
            disabledReason: getReplayVisionEditDisabledReason() ?? undefined,
            // The editor asks for AI consent on save, so the row can skip the title button's consent popover.
            onSelect: () => router.actions.push(urls.replayVisionNewScanner()),
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => <QuillCreateScannerButton acceptedLabel="New scanner" dataAttr="vision-scanner-create" />,
            },
        },
        replayVisionFeedbackAction(RESOURCE_TYPE, { order: 1, variant: 'secondary' }),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
