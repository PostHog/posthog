import { Meta, StoryFn } from '@storybook/react'

import { MessageSentimentBar, SentimentBar, SentimentTag } from './SentimentTag'

const meta: Meta = {
    title: 'Scenes-App/LLM Analytics/Sentiment',
}
export default meta

// -- SentimentTag --

const SentimentTagTemplate: StoryFn<typeof SentimentTag> = (args) => <SentimentTag {...args} />

export const TagPositive = SentimentTagTemplate.bind({})
TagPositive.args = {
    label: 'positive',
    score: 0.92,
    scores: { positive: 0.92, neutral: 0.05, negative: 0.03 },
}

export const TagNegative = SentimentTagTemplate.bind({})
TagNegative.args = {
    label: 'negative',
    score: 0.85,
    scores: { positive: 0.05, neutral: 0.1, negative: 0.85 },
}

export const TagNeutral = SentimentTagTemplate.bind({})
TagNeutral.args = {
    label: 'neutral',
    score: 0.7,
    scores: { positive: 0.15, neutral: 0.7, negative: 0.15 },
}

export const TagLoading = SentimentTagTemplate.bind({})
TagLoading.args = {
    label: 'positive',
    score: 0,
    loading: true,
}

// -- SentimentBar --

const SentimentBarTemplate: StoryFn<typeof SentimentBar> = (args) => (
    <div className="w-80">
        <SentimentBar {...args} />
    </div>
)

export const BarPositive = SentimentBarTemplate.bind({})
BarPositive.args = {
    label: 'positive',
    score: 0.88,
}

export const BarNegative = SentimentBarTemplate.bind({})
BarNegative.args = {
    label: 'negative',
    score: 0.75,
}

export const BarNeutral = SentimentBarTemplate.bind({})
BarNeutral.args = {
    label: 'neutral',
    score: 0.6,
}

export const BarFullWidth = SentimentBarTemplate.bind({})
BarFullWidth.args = {
    label: 'positive',
    score: 0.92,
    size: 'full',
}

export const BarWithTickMarks = SentimentBarTemplate.bind({})
BarWithTickMarks.args = {
    label: 'positive',
    score: 0.65,
    size: 'full',
    messages: {
        0: { label: 'positive', scores: { positive: 0.95, neutral: 0.03, negative: 0.02 } },
        1: { label: 'neutral', scores: { positive: 0.2, neutral: 0.6, negative: 0.2 } },
        2: { label: 'negative', scores: { positive: 0.05, neutral: 0.1, negative: 0.85 } },
    },
}

export const BarLoading = SentimentBarTemplate.bind({})
BarLoading.args = {
    label: 'positive',
    score: 0,
    loading: true,
}

export const BarLoadingFullWidth = SentimentBarTemplate.bind({})
BarLoadingFullWidth.args = {
    label: 'positive',
    score: 0,
    loading: true,
    size: 'full',
}

// -- MessageSentimentBar --

const MessageSentimentBarTemplate: StoryFn<typeof MessageSentimentBar> = (args) => <MessageSentimentBar {...args} />

export const MessageBarPositive = MessageSentimentBarTemplate.bind({})
MessageBarPositive.args = {
    sentiment: { label: 'positive', score: 0.9 },
}

export const MessageBarNegative = MessageSentimentBarTemplate.bind({})
MessageBarNegative.args = {
    sentiment: { label: 'negative', score: 0.8 },
}

export const MessageBarNeutral = MessageSentimentBarTemplate.bind({})
MessageBarNeutral.args = {
    sentiment: { label: 'neutral', score: 0.65 },
}
