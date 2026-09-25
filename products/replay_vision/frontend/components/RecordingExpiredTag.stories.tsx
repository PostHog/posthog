import { Meta, StoryFn } from '@storybook/react'

import { RecordingExpiredTag } from './RecordingExpiredTag'

const meta: Meta<typeof RecordingExpiredTag> = {
    title: 'Scenes-App/Replay Vision/RecordingExpiredTag',
    component: RecordingExpiredTag,
}
export default meta

// The tag a search result shows once the recordings API confirms its recording no longer exists.
// Its tooltip copy appears on hover.
export const Default: StoryFn = () => <RecordingExpiredTag />
