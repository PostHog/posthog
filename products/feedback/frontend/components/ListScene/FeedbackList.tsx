import { FeedbackItem } from '../../types'
import { FeedbackListItem } from './FeedbackListItem'

const MOCK_FEEDBACK: FeedbackItem[] = [
    {
        id: '1',
        user: 'user@example.com',
        message: 'Love the new dashboard! The insights are really helpful and the UI is much cleaner.',
        type: 'feature request',
        timestamp: '2 hours ago',
    },
    {
        id: '2',
        user: 'john@company.com',
        message: 'The search feature is a bit slow and sometimes returns irrelevant results.',
        type: 'bug',
        timestamp: '5 hours ago',
    },
    {
        id: '3',
        user: 'sarah@startup.io',
        message: 'Great product overall. Would be nice to have dark mode though.',
        type: 'feature request',
        timestamp: '1 day ago',
    },
    {
        id: '4',
        user: 'mike@tech.com',
        message: 'The onboarding process was smooth and easy to follow. Impressed!',
        type: 'question',
        timestamp: '1 day ago',
    },
    {
        id: '5',
        user: 'anna@design.co',
        message: 'Having issues with the export feature. It keeps timing out on large datasets.',
        type: 'bug',
        timestamp: '2 days ago',
    },
]

export function FeedbackList(): JSX.Element {
    return (
        <div className="space-y-2">
            {MOCK_FEEDBACK.map((feedback) => (
                <FeedbackListItem key={feedback.id} feedback={feedback} />
            ))}
        </div>
    )
}
