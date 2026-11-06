import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { AppErrorState } from './AppErrorState'
import { AppLoadingState } from './AppLoadingState'

// An app renders in whatever width the host gives its iframe, which a side panel can
// squeeze to a few hundred pixels, so let the story follow the viewport.
const HostWidth = (Story: StoryFn): ReactElement => (
    <div className="w-full">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/App states',
    decorators: [McpThemeDecorator, HostWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

export const Loading: Story = {
    render: () => <AppLoadingState />,
}

export const NoResults: Story = {
    render: () => <AppErrorState message="This app didn't get any results. Re-run the tool to try again." />,
    name: 'No results',
}
