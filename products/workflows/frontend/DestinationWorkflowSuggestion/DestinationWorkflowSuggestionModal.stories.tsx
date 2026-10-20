import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { HogFunctionTemplateType } from '~/types'

import { destinationWorkflowSuggestionLogic } from './destinationWorkflowSuggestionLogic'
import { DestinationWorkflowSuggestionModal } from './DestinationWorkflowSuggestionModal'

const CUSTOMER_IO_TEMPLATE = {
    id: 'template-customerio',
    type: 'destination',
    name: 'Customer.io',
    description: 'Identify or track events and people in Customer.io',
    icon_url: '/static/services/customerio.png',
    status: 'stable',
    free: false,
    code: '',
    code_language: 'hog',
    inputs_schema: [],
} as unknown as HogFunctionTemplateType

const meta: Meta = {
    title: 'Products/Workflows/DestinationWorkflowSuggestionModal',
    component: DestinationWorkflowSuggestionModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { waitForSelector: '.LemonModal' },
    },
}
export default meta

function Template({ events }: { events: string[] }): JSX.Element {
    const { openSuggestion } = useActions(destinationWorkflowSuggestionLogic)

    useEffect(() => {
        openSuggestion(CUSTOMER_IO_TEMPLATE, events, () => {})
    }, [openSuggestion, events])

    return <DestinationWorkflowSuggestionModal />
}

export const BuildFromPickedEvents: StoryFn = () => (
    <Template events={['signed_up', 'trial_started', 'payment_failed']} />
)

export const OnlyDefaultEvents: StoryFn = () => <Template events={[]} />
