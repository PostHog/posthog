import { IconExternal } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFeedback } from 'lib/lemon-ui/icons'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { TRACING_DOCS_URL } from './traceLinks'

const RESOURCE_TYPE = 'tracing'

interface TracingSceneMenuBarProps {
    onFeedbackClick: () => void
    onDocsLinkClick: () => void
}

export function TracingSceneMenuBar(props: TracingSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <TracingSceneMenuBarInner {...props} /> : null
}

function TracingSceneMenuBarInner({ onFeedbackClick, onDocsLinkClick }: TracingSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'feedback',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconFeedback />,
            opensFloatingUi: true,
            onSelect: onFeedbackClick,
            pinned: { order: 1, variant: 'secondary' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-documentation`,
            label: 'Documentation',
            icon: <IconExternal />,
            onSelect: () => {
                onDocsLinkClick()
                window.open(TRACING_DOCS_URL, '_blank', 'noopener,noreferrer')
            },
            pinned: { order: 2, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
