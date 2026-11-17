import { useActions, useValues } from 'kea'

import { IconPlay, IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { BRIEF_ALREADY_GENERATING_MESSAGE, pulseLogic } from './pulseLogic'
import { QuillRunBriefButton } from './QuillRunBriefButton'

const RESOURCE_TYPE = 'pulse'

export function PulseSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <PulseSceneMenuBarInner /> : null
}

function PulseSceneMenuBarInner(): JSX.Element {
    const { isGeneratingForSelectedConfig, generatedBriefLoading, selectedConfigId, dataProcessingAccepted } =
        useValues(pulseLogic)
    const { generateBrief, openConfigModal } = useActions(pulseLogic)

    const runDisabledReason = !dataProcessingAccepted
        ? 'Approve AI data processing first'
        : generatedBriefLoading
          ? 'Generating a brief'
          : isGeneratingForSelectedConfig
            ? BRIEF_ALREADY_GENERATING_MESSAGE
            : undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-config`,
            label: 'New config',
            icon: <IconPlus />,
            opensFloatingUi: true,
            onSelect: () => openConfigModal(null),
            pinned: { order: 1, variant: 'secondary' },
        },
        {
            group: 'edit',
            section: 'run',
            id: `${RESOURCE_TYPE}-menubar-run-brief`,
            label: 'Run brief now',
            icon: <IconPlay />,
            disabledReason: runDisabledReason,
            onSelect: () => generateBrief({ configId: selectedConfigId }),
            pinned: { order: 2, variant: 'primary', render: () => <QuillRunBriefButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
