import type { Meta, StoryObj } from '@storybook/react'

import { ComposerFocusCard } from './ComposerFocusCard'

const meta: Meta<typeof ComposerFocusCard> = {
    title: 'PostHog AI/Composer/Composer focus card',
    component: ComposerFocusCard,
    parameters: { layout: 'padded' },
    decorators: [
        (Story) => (
            // The side panel leaves about this much width for the composer at a 1280px window.
            <div className="max-w-[500px]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ComposerFocusCard>

export const SqlCell: Story = {
    args: {
        focus: {
            providerId: 'story',
            id: 'cell-1',
            title: 'Weekly signups by plan, excluding internal and test accounts',
            caption: 'PostHog AI can see this notebook and this cell.',
            code: "select toStartOfWeek(timestamp) as week, count() as signups\nfrom events\nwhere event = 'user signed up'\ngroup by week\norder by week",
            codeLanguage: 'sql',
        },
    },
}

export const PythonCell: Story = {
    args: {
        focus: {
            providerId: 'story',
            id: 'cell-2',
            title: 'Signup trend',
            caption: 'PostHog AI can see this notebook and this cell.',
            code: 'weekly = signups.set_index("week")\nweekly["change"] = weekly["signups"].pct_change()\nweekly',
            codeLanguage: 'python',
        },
    },
}

export const CompactAboveThread: Story = {
    args: {
        compact: true,
        focus: {
            providerId: 'story',
            id: 'cell-2',
            title: 'Signup trend',
            code: 'weekly = signups.set_index("week")',
            codeLanguage: 'python',
        },
    },
}
