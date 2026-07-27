import type { Meta, StoryObj } from '@storybook/react'

import { PersonType } from '~/types'

import { TranscriptChat } from './TranscriptChat'

const meta: Meta<typeof TranscriptChat> = {
    title: 'Scenes-App/User Interviews/Transcript Chat',
    component: TranscriptChat,
}
export default meta

type Story = StoryObj<typeof TranscriptChat>

const fakePerson: PersonType = {
    id: '1',
    uuid: '00000000-0000-0000-0000-000000000000',
    distinct_ids: ['alex@example.com'],
    properties: {
        name: 'Alex Example',
        email: 'alex@example.com',
    },
    created_at: '2024-01-15T12:00:00Z',
    is_identified: true,
}

const multiTurnTranscript = [
    'AI: Thanks for making the time. Mind if I ask a few questions about your workflow? Should take about five minutes.',
    'User: Yep, go ahead.',
    "AI: I see you've created a bunch of insights in the last month through the MCP integration but never via the web UI. Do you ever use the web UI at all?",
    'User: Honestly, just the MCP integration for me. I do most of my work inside another tool and pull data in from there.',
    'AI: That makes sense. Walk me through the most recent thing you were trying to figure out.',
    'User: I was trying to figure out the install rate on iOS, because it matters a lot for our product right now.',
    'AI: Why reach for MCP for that instead of opening the dashboard yourself?',
    'User: Having one tool that can synthesize across platforms is really valuable. I would not know where to look in the UI on my own.',
].join('\n')

const inlineNoNewlinesTranscript =
    'AI: Hey there, thanks for joining. Could you describe a typical week for you? User: Sure, mostly product work. AI: Where do you feel the most friction? User: Honestly, switching between tools — every context switch costs me momentum.'

const speakerKeywordInBodyTranscript =
    'AI: When you say the User: experience felt slow, do you mean the loading time or the time-to-first-interaction?\nUser: The loading time.\nAI: Got it.'

const namedSpeakerTranscript = `Assistant: Welcome. Before we dive in, could you tell me what brought you to the product?
Interviewee: A friend recommended it. We needed a way to track usage without piecing things together ourselves.
Assistant: And what does success look like for your team in the next quarter?
Interviewee: Cutting the time it takes to answer a "did this feature move the needle" question from days to minutes.`

const noSpeakerTranscript = `This transcript did not include any speaker labels — perhaps because the
transcription provider could not segment speakers. The fallback renderer
should still show this content as plain markdown so nothing is lost.

- It may even contain markdown lists.
- Or **bold text**.`

const leadingProseTranscript = `Interview started 2026-05-29 with Alex Example.
AI: Thanks for joining. Walk me through your last week.
User: Mostly product work — Monday dashboards, Tuesday writing, Thursday customer calls.`

export const KnownPerson: Story = {
    args: {
        transcript: multiTurnTranscript,
        person: fakePerson,
        identifier: 'alex@example.com',
    },
}

export const IdentifierOnly: Story = {
    args: {
        transcript: multiTurnTranscript,
        person: null,
        identifier: 'jordan@example.com',
    },
}

export const InlineNoNewlines: Story = {
    args: {
        transcript: inlineNoNewlinesTranscript,
        person: fakePerson,
        identifier: 'alex@example.com',
    },
}

export const SpeakerKeywordInBody: Story = {
    args: {
        transcript: speakerKeywordInBodyTranscript,
        person: fakePerson,
        identifier: 'alex@example.com',
    },
}

export const AssistantAndInterviewee: Story = {
    args: {
        transcript: namedSpeakerTranscript,
        person: fakePerson,
        identifier: 'alex@example.com',
    },
}

export const FallbackNoSpeakerMarkers: Story = {
    args: {
        transcript: noSpeakerTranscript,
        person: null,
        identifier: 'unknown',
    },
}

export const FallbackLeadingProse: Story = {
    args: {
        transcript: leadingProseTranscript,
        person: fakePerson,
        identifier: 'alex@example.com',
    },
}

export const NonEmailIdentifier: Story = {
    args: {
        transcript: multiTurnTranscript,
        person: null,
        identifier: 'distinct_id_abc123',
    },
}
