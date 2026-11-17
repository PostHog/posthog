import { router } from 'kea-router'

import { IconLetter } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'transactional-email-log-entry'

interface TransactionalEmailLogEntrySceneMenuBarProps {
    templateId: string | null | undefined
}

export function TransactionalEmailLogEntrySceneMenuBar(
    props: TransactionalEmailLogEntrySceneMenuBarProps
): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <TransactionalEmailLogEntrySceneMenuBarInner {...props} /> : null
}

function TransactionalEmailLogEntrySceneMenuBarInner({
    templateId,
}: TransactionalEmailLogEntrySceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = templateId
        ? [
              {
                  group: 'view',
                  id: `${RESOURCE_TYPE}-menubar-open-template`,
                  label: 'Open email',
                  icon: <IconLetter />,
                  onSelect: () => router.actions.push(urls.transactionalTemplate(templateId)),
                  pinned: {
                      order: 1,
                      variant: 'secondary',
                      dataAttr: 'transactional-email-log-entry-open-template',
                  },
              },
          ]
        : []

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
