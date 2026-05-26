import type { Meta, StoryObj } from '@storybook/react'

import { TranscriptView } from './TranscriptView'

interface TranscriptViewProps {
    transcript: string
}

const meta: Meta<TranscriptViewProps> = {
    title: 'Scenes-App/User Interviews/TranscriptView',
    component: TranscriptView,
    render: ({ transcript }) => (
        <div className="max-w-2xl">
            <TranscriptView transcript={transcript} />
        </div>
    ),
}
export default meta
type Story = StoryObj<TranscriptViewProps>

export const AIAndUser: Story = {
    args: {
        transcript: [
            'AI: Thanks for joining us today. To start, can you tell me a bit about how you currently track product analytics?',
            'User: Sure — we use PostHog for funnels and a bit of session replay, but the bulk of dashboards lives in a separate BI tool.',
            'AI: Got it. What pushed you toward keeping dashboards outside of PostHog?',
            'User: Mostly historical reasons. The BI tool was already set up when I joined and the SQL team owns it.',
        ].join('\n'),
    },
}

export const NamedParticipants: Story = {
    args: {
        transcript: [
            'Interviewer: Walk me through the last time you set up a new dashboard.',
            'Cory Slater: I duplicated an existing one and swapped the events. Quicker than starting blank.',
            'Interviewer: Anything friction-y about that flow?',
            "Cory Slater: The filter chips on the duplicated tiles still pointed at the old team's properties — took me a minute to spot.",
        ].join('\n'),
    },
}

export const MultiLineTurns: Story = {
    args: {
        transcript: [
            'AI: What would have made the migration easier?',
            'User: A few things.',
            'First, clearer docs about which properties are person-on-events vs query-time.',
            'Second, an example of the same query expressed in both modes.',
            "AI: That's helpful — we've heard the same from a couple of other folks.",
        ].join('\n'),
    },
}

export const FreeFormFallback: Story = {
    args: {
        transcript:
            'This is just a block of free-form notes that someone pasted in. There are no speaker prefixes here, so the component should fall back to rendering it as pre-wrapped plain text instead of inventing turns.',
    },
}

export const SinglePrefixBelowThreshold: Story = {
    args: {
        transcript:
            'Note: this transcript only has one prefixed line, so it should fall back to plain rendering and not split into a single styled turn.',
    },
}
