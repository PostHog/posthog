import { Meta, StoryObj } from '@storybook/react'
import { ComponentProps, useState } from 'react'

import { CardsPreview } from './CardsPreview'

type PreviewArgs = Pick<ComponentProps<typeof CardsPreview>, 'loading' | 'setupSelected' | 'missingSpec'>

function InteractiveCardsPreview({
    loading: initialLoading,
    setupSelected: initialSetupSelected,
    missingSpec,
}: PreviewArgs): JSX.Element {
    const [loading, setLoading] = useState(initialLoading)
    const [setupSelected, setSetupSelected] = useState(initialSetupSelected)
    return (
        <CardsPreview
            loading={loading}
            setupSelected={setupSelected}
            missingSpec={missingSpec}
            onLoadingChange={setLoading}
            onSetupSelected={() => setSetupSelected(true)}
        />
    )
}

const meta: Meta<typeof CardsPreview> = {
    title: 'Marketing Analytics/Dashboard/Metric cards',
    component: CardsPreview,
    args: { loading: false, setupSelected: false, missingSpec: false },
    render: ({ loading, setupSelected, missingSpec }) => (
        // useState reads its initial value on mount only, so the key remounts the preview when a Storybook control changes it.
        <InteractiveCardsPreview
            key={`${loading}-${setupSelected}`}
            loading={loading}
            setupSelected={setupSelected}
            missingSpec={missingSpec}
        />
    ),
}
export default meta
type Story = StoryObj<typeof meta>

export const Interactive: Story = {}
export const Loading: Story = {
    args: { loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const MissingSpec: Story = { args: { missingSpec: true } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[32.5rem] max-w-full">
                {/* A 520 px scene models the space beside an open side panel. */}
                <Story />
            </div>
        ),
    ],
}
