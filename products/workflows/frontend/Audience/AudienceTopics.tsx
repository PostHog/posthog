import { useActions, useValues } from 'kea'

import { IconDownload, IconEllipsis, IconExternal } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { customerIOImportLogic } from '../OptOuts/customerIOImportLogic'
import { CustomerIOImportModal } from '../OptOuts/CustomerIOImportModal'
import { NewCategoryButton } from '../OptOuts/NewCategoryButton'
import { OptOutCategories } from '../OptOuts/OptOutCategories'
import { OptOutList } from '../OptOuts/OptOutList'
import { optOutSceneLogic } from '../OptOuts/optOutSceneLogic'
import { topicVocabularyLogic } from '../OptOuts/topicVocabularyLogic'

export function AudienceTopics(): JSX.Element {
    const { words } = useValues(topicVocabularyLogic)

    return (
        <div className="flex flex-col gap-8" data-attr="audience-topics">
            <section className="flex flex-col gap-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="max-w-2xl">
                        <h2 className="text-xl font-semibold m-0">{words.topics.heading}</h2>
                        <p className="text-muted m-0">
                            The kinds of messages a recipient can subscribe to or unsubscribe from. Recipients see
                            topics on their preferences page, and your app sets preferences by topic key.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <NewCategoryButton />
                        <TopicsMoreMenu />
                    </div>
                </div>
                <OptOutCategories />
            </section>

            <section className="flex flex-col gap-2">
                <div>
                    <h2 className="text-xl font-semibold m-0">{words.unsubscribedList.heading}</h2>
                    <p className="text-muted m-0">{words.unsubscribedList.description}</p>
                </div>
                <OptOutList />
            </section>

            <CustomerIOImportModal />
        </div>
    )
}

function TopicsMoreMenu(): JSX.Element {
    const { user } = useValues(userLogic)
    const { preferencesUrlLoading } = useValues(optOutSceneLogic)
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
                icon={<IconEllipsis />}
                size="small"
                loading={preferencesUrlLoading}
            />
        </LemonMenu>
    )
}
