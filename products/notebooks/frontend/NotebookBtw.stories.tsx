import type { Meta, StoryObj } from '@storybook/react'

import { NotebookBtw } from './NotebookBtw'

const meta: Meta<typeof NotebookBtw> = {
    title: 'Scenes-App/Notebooks/Btw mode',
    component: NotebookBtw,
    parameters: {
        testOptions: { snapshotTargetSelector: '.LemonModal' },
    },
    args: {
        session: {
            panelId: 'notebook-btw-story',
            context: {
                markdown: '# Weekly review\n\nActivation improved after the onboarding changes.',
                selectedMarkdown: 'Activation improved after the onboarding changes.',
            },
        },
        onClose: () => {},
    },
}

export default meta
type Story = StoryObj<typeof NotebookBtw>

export const Default: Story = {}
