import { useActions, useValues } from 'kea'

import { IconDownload, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
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
                            The kinds of email a recipient can subscribe to or unsubscribe from. Recipients see topics
                            on their preferences page, and your app sets preferences by topic key.
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
        <More
            data-attr="audience-topics-more"
            overlay={
                <>
                    <LemonButton
                        fullWidth
                        icon={<IconDownload />}
                        onClick={() => openImportModal()}
                        tooltip="Import topics and preferences from Customer.io"
                    >
                        Import from Customer.io
                    </LemonButton>
                    <LemonButton
                        fullWidth
                        icon={<IconExternal />}
                        onClick={() => openPreferencesPage()}
                        loading={preferencesUrlLoading}
                        disabledReason={!user?.email ? 'Your account has no email address' : undefined}
                        tooltip="Open the preferences page your own address sees, in a new tab"
                    >
                        Preview preferences page
                    </LemonButton>
                </>
            }
        />
    )
}
