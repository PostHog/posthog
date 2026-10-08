import { useActions, useValues } from 'kea'

import { IconDownload, IconEllipsis, IconExternal } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { customerIOImportLogic } from '../OptOuts/customerIOImportLogic'
import { optOutSceneLogic } from '../OptOuts/optOutSceneLogic'

export function AudienceTopicsMoreMenu(): JSX.Element {
    const { user } = useValues(userLogic)
    const { previewingPreferencesPage } = useValues(optOutSceneLogic)
    const { openPreferencesPage } = useActions(optOutSceneLogic)
    const { openImportModal } = useActions(customerIOImportLogic)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Import from Customer.io',
                    icon: <IconDownload />,
                    tooltip: 'Import topics and preferences from Customer.io',
                    onClick: () => openImportModal(),
                },
                {
                    label: 'Preview preferences page',
                    icon: <IconExternal />,
                    tooltip: 'Open the preferences page your own address sees, in a new tab',
                    disabledReason: !user?.email ? 'Your account has no email address' : undefined,
                    onClick: () => openPreferencesPage(),
                },
            ]}
            placement="bottom-end"
        >
            <LemonButton
                data-attr="audience-topics-more"
                aria-label="More topic actions"
                tooltip="More"
                icon={<IconEllipsis />}
                size="small"
                loading={previewingPreferencesPage}
            />
        </LemonMenu>
    )
}
