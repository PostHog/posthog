import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { expect } from 'storybook/test'

import { NotebookAppBlock } from './NotebookAppBlock'

const meta: Meta<typeof NotebookAppBlock> = {
    title: 'Scenes-App/Notebooks/App block',
    component: NotebookAppBlock,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        stale: false,
        variables: [],
        canInteract: false,
        onInput: () => {},
        onCellOutput: () => {},
    },
}
export default meta

export const TextImages: StoryObj<typeof NotebookAppBlock> = {
    args: {
        block: {
            id: 'text',
            kind: 'text',
            tab_id: 'overview',
            text: '![Preview](https://example.com/preview.png)',
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByRole('link', { name: /Preview/ })).toHaveAttribute(
            'href',
            'https://example.com/preview.png'
        )
        await expect(canvasElement.querySelector('img')).toBeNull()
    },
}
