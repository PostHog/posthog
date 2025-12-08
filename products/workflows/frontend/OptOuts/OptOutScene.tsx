import { useActions, useValues } from 'kea'

import { IconDownload, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { CustomerIOImportModal } from './CustomerIOImportModal'
import { OptOutCategories } from './OptOutCategories'
import { OptOutList } from './OptOutList'
import { customerIOImportLogic } from './customerIOImportLogic'
import { optOutSceneLogic } from './optOutSceneLogic'

export function OptOutScene(): JSX.Element {
    const { user } = useValues(userLogic)

    const { preferencesUrlLoading } = useValues(optOutSceneLogic)
    const { openPreferencesPage } = useActions(optOutSceneLogic)
    const { openImportModal } = useActions(customerIOImportLogic)

    return (
        <div className="space-y-8">
            <div>
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-xl font-semibold">Message categories</h2>
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => openImportModal()}
                            icon={<IconDownload />}
                            tooltip="Import subscription topics and preferences from Customer.io"
                        >
                            Import from Customer.io
                        </LemonButton>
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
                </div>
                <OptOutCategories />
            </div>

            <div>
                <h2 className="text-xl font-semibold">Marketing opt-out list</h2>
                <p className="mt-6">Message recipients who have opted out of all marketing messages</p>
                <OptOutList />
            </div>

            <CustomerIOImportModal />
        </div>
    )
}
