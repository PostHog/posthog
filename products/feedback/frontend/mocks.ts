import { FeedbackItem } from './models'

export const MOCK_FEEDBACK_ITEMS: FeedbackItem[] = [
    {
        id: '1',
        content: 'Love the new dashboard! The insights are really helpful and the UI is much cleaner.',
        category: { id: 'feature', name: 'feature' },
        topic: { id: 'dashboard', name: 'Dashboard' },
        created_at: '2 hours ago',
        status: { id: 'visible', name: 'Visible' },
        assignment: null,
        attachments: [],
    },
]
