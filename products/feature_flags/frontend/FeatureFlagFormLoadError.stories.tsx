import { Meta, StoryFn } from '@storybook/react'

import { FeatureFlagFormLoadError } from './FeatureFlagFormLoadError'

const meta: Meta<typeof FeatureFlagFormLoadError> = {
    title: 'Scenes-App/Feature Flags/Feature Flag Form Load Error',
    component: FeatureFlagFormLoadError,
    args: {
        error: new TypeError('Failed to fetch dynamically imported module: /static/chunk.js'),
        teamId: 1,
        onRetry: () => {},
        hasUnsavedChanges: true,
    },
}
export default meta

export const Default: StoryFn<typeof FeatureFlagFormLoadError> = (args) => <FeatureFlagFormLoadError {...args} />

// The reload guard can surface this on a clean form, where there is nothing to discard.
export const NoUnsavedChanges: StoryFn<typeof FeatureFlagFormLoadError> = (args) => (
    <FeatureFlagFormLoadError {...args} hasUnsavedChanges={false} />
)

// The scene is about this wide with the nav sidebar and a side panel open, where the actions wrap.
export const Narrow: StoryFn<typeof FeatureFlagFormLoadError> = (args) => (
    <div className="w-[520px]">
        <FeatureFlagFormLoadError {...args} />
    </div>
)
