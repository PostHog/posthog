import { kea, key, path, props } from 'kea'

export interface FeedbackItemSceneLogicProps {
    feedbackItemId: string
}

export const feedbackItemSceneLogic = kea([
    path((key) => ['products', 'feedback', 'scenes', 'FeedbackItemScene', 'feedbackItemSceneLogic', key]),
    props({} as FeedbackItemSceneLogicProps),
    key((props) => props.feedbackItemId),
])
