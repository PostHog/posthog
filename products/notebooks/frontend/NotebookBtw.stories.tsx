import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { MarkdownNotebook } from 'lib/components/MarkdownNotebook/MarkdownNotebook'

import { NotebookBtwLayout } from './NotebookBtwLayout'
import type { NotebookBtwSession } from './notebookBtwLogic'

const markdown = `# Weekly activation review

Activation improved after the onboarding changes. **Signup completion** is up, while workspace setup is steady.

## Questions for the team

- Which onboarding step improved the most?
- Do the results hold for new workspaces?
- What should we investigate next?

## Next steps

Compare this week's signup funnel with last week's and review the sessions where setup was abandoned.`

function NotebookBtwExample({ session: initialSession }: { session: NotebookBtwSession | null }): JSX.Element {
    const [session, setSession] = useState(initialSession)
    const [value, setValue] = useState(markdown)

    return (
        <NotebookBtwLayout session={session} onClose={() => setSession(null)}>
            <MarkdownNotebook
                value={value}
                onChange={setValue}
                onAskAI={() => {}}
                onBtw={(context) => setSession({ panelId: 'notebook-btw-story', context })}
            />
        </NotebookBtwLayout>
    )
}

const meta: Meta<typeof NotebookBtwLayout> = {
    title: 'Scenes-App/Notebooks/BTW',
    component: NotebookBtwLayout,
    render: ({ session }) => <NotebookBtwExample session={session} />,
    args: {
        session: {
            panelId: 'notebook-btw-story',
            context: {
                markdown,
                selectedMarkdown: 'Activation improved after the onboarding changes.',
            },
        },
        onClose: () => {},
    },
}

export default meta
type Story = StoryObj<typeof NotebookBtwLayout>

export const Default: Story = {}

export const Narrow: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.LemonModal' } },
    decorators: [
        (Story) => (
            <div className="max-w-2xl">
                <Story />
            </div>
        ),
    ],
}
