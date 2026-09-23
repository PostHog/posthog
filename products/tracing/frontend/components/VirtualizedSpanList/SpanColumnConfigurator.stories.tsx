import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

import { SpanColumnConfigurator } from './SpanColumnConfigurator'

const ATTRIBUTE_KEYS = ['http.target', 'http.method', 'db.statement', 'messaging.system']

const meta: Meta<typeof SpanColumnConfigurator> = {
    title: 'Products/Tracing/SpanColumnConfigurator',
    component: SpanColumnConfigurator,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tracing/spans/attributes': () => [
                    200,
                    { results: ATTRIBUTE_KEYS.map((name) => ({ name })), count: ATTRIBUTE_KEYS.length },
                ],
            },
        }),
    ],
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof SpanColumnConfigurator>

export const Default: Story = {}

export const Open: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Configure columns'))
        await within(document.body).findByText('Add an attribute column')
    },
}
