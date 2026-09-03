import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { RESOLVE_REASON_OPTIONS, ResolveReasonValue } from '../../utils/dismissalReasons'
import { HotkeyRadio } from './HotkeyRadio'

const meta: Meta<typeof HotkeyRadio> = {
    title: 'Scenes-App/Inbox/HotkeyRadio',
    component: HotkeyRadio,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof HotkeyRadio>

function ResolveReasons(): JSX.Element {
    const [value, setValue] = useState<ResolveReasonValue | null>('pr_merged')
    return <HotkeyRadio value={value} onChange={setValue} options={RESOLVE_REASON_OPTIONS} />
}

export const WithSelection: Story = {
    render: () => <ResolveReasons />,
}
