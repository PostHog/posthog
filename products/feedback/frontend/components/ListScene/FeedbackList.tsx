import { useValues } from 'kea'

import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'

import { filtersLogic } from '../../logics/filtersLogic'
import { FeedbackListItem } from './FeedbackListItem'

export function FeedbackList(): JSX.Element {
    const { feedbackItems, feedbackItemsLoading } = useValues(filtersLogic)

    return (
        <div className="bg-bg-light border rounded relative">
            <LemonTableLoader loading={feedbackItemsLoading} placement="top" />
            {feedbackItems.map((feedback) => (
                <FeedbackListItem key={feedback.id} feedback={feedback} />
            ))}
        </div>
    )
}
