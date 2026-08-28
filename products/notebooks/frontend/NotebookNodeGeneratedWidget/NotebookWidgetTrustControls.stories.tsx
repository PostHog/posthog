import type { Meta, StoryObj } from '@storybook/react'

import { NotebookWidgetTrustControls, type NotebookWidgetTrustControlsProps } from './NotebookWidgetTrustControls'

type Story = StoryObj<NotebookWidgetTrustControlsProps>

const meta: Meta<NotebookWidgetTrustControlsProps> = {
    title: 'Products/Notebooks/Notebook widget trust controls',
    component: NotebookWidgetTrustControls,
    args: {
        buildHash: 'a'.repeat(64),
        canTrustScopes: true,
        notebookTrusted: false,
        projectTrusted: false,
        onRun: () => undefined,
        onViewSource: () => undefined,
        onNotebookTrustedChange: () => undefined,
        onProjectTrustedChange: () => undefined,
    },
}

export default meta

export const Gate: Story = {
    args: { variant: 'gate' },
}

export const Toolbar: Story = {
    args: { variant: 'toolbar' },
}

export const MissingBuildHash: Story = {
    args: { buildHash: null, variant: 'gate' },
}
