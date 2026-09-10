import { Meta, StoryObj } from '@storybook/react'

import { SelfDrivingIntroModal } from './SelfDrivingIntroModal'

const meta: Meta<typeof SelfDrivingIntroModal> = {
    title: 'Products/Signals/Self-driving intro modal',
    component: SelfDrivingIntroModal,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof SelfDrivingIntroModal>

export const Default: Story = {
    args: {
        isOpen: true,
        inline: true,
        onClose: () => {},
    },
}
