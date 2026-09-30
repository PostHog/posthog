import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import type { HogFunctionTemplateWithSubTemplateType } from '~/types'

import { DestinationCrossSellStep, destinationCrossSellLogic } from './destinationCrossSellLogic'
import { DestinationCrossSellModal } from './DestinationCrossSellModal'

const CUSTOMERIO_TEMPLATE = {
    id: 'template-customerio',
    name: 'Customer.io',
    type: 'destination',
    status: 'stable',
} as HogFunctionTemplateWithSubTemplateType

function OpenedModal({ step }: { step: DestinationCrossSellStep }): JSX.Element {
    const { openModal, setStep } = useActions(destinationCrossSellLogic)

    useEffect(() => {
        openModal(CUSTOMERIO_TEMPLATE, '/functions/new/template-customerio')
        setStep(step)
    }, [openModal, setStep, step])

    return <DestinationCrossSellModal />
}

const meta: Meta<typeof OpenedModal> = {
    title: 'Scenes-App/Workflows/Destination cross-sell modal',
    component: OpenedModal,
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            waitForSelector: '.LemonModal',
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta

type Story = StoryObj<typeof OpenedModal>

export const Intro: Story = {
    args: { step: 'intro' },
}

export const Describe: Story = {
    args: { step: 'describe' },
}
