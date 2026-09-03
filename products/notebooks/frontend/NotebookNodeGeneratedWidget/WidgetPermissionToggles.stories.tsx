import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { WidgetPermissions } from './widgetPermissions'
import { WidgetPermissionToggles } from './WidgetPermissionToggles'

function PermissionDemo({ initial }: { initial: WidgetPermissions }): JSX.Element {
    const [permissions, setPermissions] = useState(initial)
    return (
        <div className="max-w-160 p-4">
            <WidgetPermissionToggles value={permissions} onChange={setPermissions} />
        </div>
    )
}

const meta: Meta<typeof PermissionDemo> = {
    title: 'Products/Notebooks/Generated widget permissions',
    component: PermissionDemo,
}

export default meta
type Story = StoryObj<typeof PermissionDemo>

export const NotebookDataOnly: Story = {
    args: { initial: { notebookData: true, hogqlQueries: false, toolCalls: false } },
}

export const LiveHogQL: Story = {
    args: { initial: { notebookData: false, hogqlQueries: true, toolCalls: false } },
}

export const ToolPoweredAction: Story = {
    args: { initial: { notebookData: false, hogqlQueries: false, toolCalls: true } },
}

export const NotebookAndLivePostHogData: Story = {
    args: { initial: { notebookData: true, hogqlQueries: true, toolCalls: true } },
}
