import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CreatePrModal } from './components/CreatePrModal'
import { InboxGroupedReportsTab } from './components/InboxGroupedReportsTab'
import { InboxReportsTab } from './components/InboxReportsTab'
import { InboxScoutsTab } from './components/InboxScoutsTab'
import { InboxSettingsTab } from './components/InboxSettingsTab'
import { v2InboxLogic } from './v2InboxLogic'

export const scene: SceneExport = {
    component: V2InboxScene,
    logic: v2InboxLogic,
}

export function V2InboxScene(): JSX.Element {
    const { activeTab, layout, prModalTarget } = useValues(v2InboxLogic)
    const { setTab, closePrModal, confirmPrModal } = useActions(v2InboxLogic)

    useKeyboardHotkeys(
        {
            // The modal's selects and buttons aren't inputs, so the shortcut would fire behind it
            f: {
                action: () => router.actions.push(urls.v2Focus()),
                disabled: prModalTarget !== null || activeTab !== 'reports',
            },
        },
        [prModalTarget, activeTab]
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Inbox"
                description="Issues and opportunities found in your product, ready to review"
                resourceType={{ type: 'inbox' }}
            />

            {/* The tab bar spans the scene; each tab's content stays in the centered column */}
            <LemonTabs
                activeKey={activeTab}
                onChange={setTab}
                sceneInset
                data-attr="v2-inbox-tabs"
                tabs={[
                    {
                        key: 'reports',
                        label: 'Reports',
                        content: (
                            <div className="mx-auto w-full max-w-4xl">
                                {layout === 'grouped' ? <InboxGroupedReportsTab /> : <InboxReportsTab />}
                            </div>
                        ),
                    },
                    {
                        key: 'scouts',
                        label: 'Scouts',
                        content: (
                            <div className="mx-auto w-full max-w-4xl">
                                <InboxScoutsTab />
                            </div>
                        ),
                    },
                    {
                        key: 'settings',
                        label: 'Settings',
                        content: (
                            <div className="mx-auto w-full max-w-4xl">
                                <InboxSettingsTab />
                            </div>
                        ),
                    },
                ]}
            />

            <CreatePrModal
                isOpen={prModalTarget !== null}
                flagKey={prModalTarget?.flagKey ?? ''}
                onClose={closePrModal}
                onConfirm={confirmPrModal}
            />
        </SceneContent>
    )
}

export default V2InboxScene
