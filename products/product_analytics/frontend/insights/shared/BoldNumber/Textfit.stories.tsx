import type { Meta, StoryObj } from '@storybook/react'

import { Textfit, TextfitProps } from './Textfit'

type Story = StoryObj<TextfitProps>
const meta: Meta<TextfitProps> = {
    title: 'Lemon UI/TextFit',
    component: Textfit,
    tags: ['autodocs'],
    args: {
        min: 20,
        max: 150,
        children: '10000000',
    },
    render: (props) => {
        return (
            <div className="resize w-100 h-50 overflow-hidden border rounded">
                <Textfit {...props} />
            </div>
        )
    },
}
export default meta

export const Basic: Story = {
    args: {},
}
