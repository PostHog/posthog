import { CustomerIOImportModal } from '../OptOuts/CustomerIOImportModal'
import { NewCategoryButton } from '../OptOuts/NewCategoryButton'
import { OptOutCategories } from '../OptOuts/OptOutCategories'
import { OptOutList } from '../OptOuts/OptOutList'
import { AudienceTopicsMoreMenu } from './AudienceTopicsMoreMenu'

export function AudienceTopics(): JSX.Element {
    return (
        <div className="flex flex-col gap-8" data-attr="audience-topics">
            <section className="flex flex-col gap-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="max-w-2xl">
                        <h2 className="text-xl font-semibold m-0">Topics</h2>
                        <p className="text-muted m-0">
                            The kinds of messages a recipient can subscribe to or unsubscribe from. Recipients see
                            topics on their preferences page, and your app sets preferences by topic key.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <NewCategoryButton />
                        <AudienceTopicsMoreMenu />
                    </div>
                </div>
                <OptOutCategories />
            </section>

            <section className="flex flex-col gap-2">
                <div>
                    <h2 className="text-xl font-semibold m-0">Unsubscribed from all marketing</h2>
                    <p className="text-muted m-0">
                        Recipients who left every marketing topic at once. They still get transactional messages.
                    </p>
                </div>
                <OptOutList />
            </section>

            <CustomerIOImportModal />
        </div>
    )
}
