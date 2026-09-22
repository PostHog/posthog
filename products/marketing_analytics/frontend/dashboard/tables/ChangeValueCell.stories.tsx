import { Meta, StoryObj } from '@storybook/react'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { ChangeValueCell } from './ChangeValueCell'

const meta: Meta<typeof ChangeValueCell> = {
    title: 'Scenes-App/Marketing analytics/Dashboard/Change value cell',
    component: ChangeValueCell,
    args: { currency: CurrencyCode.USD, compare: true },
}
export default meta
type Story = StoryObj<typeof meta>

export const Number: Story = { args: { value: [150, 100] } }
export const Rate: Story = { args: { value: [0.1, 0.08], kind: 'percentage' } }
export const BounceRate: Story = { args: { value: [0.2, 0.3], kind: 'percentage', reverseColors: true } }
export const Duration: Story = { args: { value: [90, 60], kind: 'duration' } }
export const Currency: Story = { args: { value: [12.5, 10], kind: 'currency' } }
export const NoBaseline: Story = { args: { value: [0, null] } }
export const Unavailable: Story = { args: { value: null } }
export const RoundedFlat: Story = { args: { value: [0.10001, 0.1], kind: 'percentage' } }
