import type { Meta, StoryObj } from '@storybook/react'
import type { ComponentProps } from 'react'

import { MessageSentimentBar, SentimentBar, SentimentTag } from './SentimentTag'

const meta: Meta = {
    title: 'Scenes-App/LLM Analytics/Sentiment',
}
export default meta

// -- SentimentTag --

export const TagPositive: StoryObj<typeof SentimentTag> = {
    render: (args) => <SentimentTag {...args} />,
    args: {
        label: 'positive',
        score: 0.92,
        scores: { positive: 0.92, neutral: 0.05, negative: 0.03 },
    },
}

export const TagNegative: StoryObj<typeof SentimentTag> = {
    render: (args) => <SentimentTag {...args} />,
    args: {
        label: 'negative',
        score: 0.85,
        scores: { positive: 0.05, neutral: 0.1, negative: 0.85 },
    },
}

export const TagNeutral: StoryObj<typeof SentimentTag> = {
    render: (args) => <SentimentTag {...args} />,
    args: {
        label: 'neutral',
        score: 0.7,
        scores: { positive: 0.15, neutral: 0.7, negative: 0.15 },
    },
}

export const TagLoading: StoryObj<typeof SentimentTag> = {
    render: (args) => <SentimentTag {...args} />,
    args: {
        label: 'positive',
        score: 0,
    },
}

// -- SentimentBar --

const renderSentimentBar = (args: ComponentProps<typeof SentimentBar>): JSX.Element => (
    <div className="w-80">
        <SentimentBar {...args} />
    </div>
)

export const BarPositive: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'positive',
        score: 0.88,
    },
}

export const BarNegative: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'negative',
        score: 0.75,
    },
}

export const BarNeutral: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'neutral',
        score: 0.6,
    },
}

export const BarFullWidth: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'positive',
        score: 0.92,
        size: 'full',
    },
}

export const BarWithTickMarks: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'positive',
        score: 0.65,
        size: 'full',
        messages: {
            0: { label: 'positive', scores: { positive: 0.95, neutral: 0.03, negative: 0.02 } },
            1: { label: 'neutral', scores: { positive: 0.2, neutral: 0.6, negative: 0.2 } },
            2: { label: 'negative', scores: { positive: 0.05, neutral: 0.1, negative: 0.85 } },
        },
    },
}

export const BarLoading: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'positive',
        score: 0,
    },
}

export const BarLoadingFullWidth: StoryObj<typeof SentimentBar> = {
    render: renderSentimentBar,
    args: {
        label: 'positive',
        score: 0,
        size: 'full',
    },
}

// -- MessageSentimentBar --

export const MessageBarPositive: StoryObj<typeof MessageSentimentBar> = {
    render: (args) => <MessageSentimentBar {...args} />,
    args: {
        sentiment: { label: 'positive', score: 0.9 },
    },
}

export const MessageBarNegative: StoryObj<typeof MessageSentimentBar> = {
    render: (args) => <MessageSentimentBar {...args} />,
    args: {
        sentiment: { label: 'negative', score: 0.8 },
    },
}

export const MessageBarNeutral: StoryObj<typeof MessageSentimentBar> = {
    render: (args) => <MessageSentimentBar {...args} />,
    args: {
        sentiment: { label: 'neutral', score: 0.65 },
    },
}
