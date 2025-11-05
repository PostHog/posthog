import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { OptOutCategories } from './OptOutCategories'
import { OptOutList } from './OptOutList'
import { optOutSceneLogic } from './optOutSceneLogic'

export function OptOutScene(): JSX.Element {
    const { user } = useValues(userLogic)

    const { preferencesUrlLoading } = useValues(optOutSceneLogic)
    const { openPreferencesPage } = useActions(optOutSceneLogic)

    return (
        <div className="space-y-8">
            <div>
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-xl font-semibold">Message categories</h2>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openPreferencesPage()}
                        loading={preferencesUrlLoading}
                        disabled={!user?.email}
                        tooltip={
                            !user?.email
                                ? 'User email not available'
                                : 'Generate an unsubscribe link for your email and open it in a new tab'
                        }
                        icon={<IconExternal />}
                    >
                        Preview opt-out page
                    </LemonButton>
                </div>
                <OptOutCategories />
            </div>

            <div>
                <h2 className="text-xl font-semibold">Marketing opt-out list</h2>
                <p className="mt-6">Message recipients who have opted out of all marketing messages</p>
                <OptOutList />
            </div>
        </div>
    )
}
