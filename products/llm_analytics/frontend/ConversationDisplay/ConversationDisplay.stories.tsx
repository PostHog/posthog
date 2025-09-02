import { Meta, StoryFn } from '@storybook/react'

import { ConversationDisplay as ConversationDisplayComponent } from './ConversationDisplay'

const meta: Meta<typeof ConversationDisplayComponent> = {
    title: 'Scenes-App/LLM Analytics/Conversation Display',
    component: ConversationDisplayComponent,
}
export default meta

const Template: StoryFn = ({ eventProperties }) => {
    return <ConversationDisplayComponent eventProperties={eventProperties} />
}

export const Basic = Template.bind({})
Basic.args = {
    eventProperties: {
        $ai_input: [
            { role: 'system', content: 'You are a good bot.' },
            { role: 'user', content: 'Hello!' },
            { role: 'assistant', content: 'Hi there!' },
            { role: 'user', content: 'How are you?' },
        ],
        $ai_output: {
            choices: [{ role: 'assistant', content: 'I am doing well, thank you!' }],
        },
        $ai_input_tokens: 8,
        $ai_output_tokens: 6,
        $ai_latency: 0.123,
        $ai_total_cost_usd: 0.0007,
        $ai_model: 'gpt-9',
        $ai_http_status: 200,
    },
}

export const Markdown = Template.bind({})
Markdown.args = {
    eventProperties: {
        $ai_input: [
            { role: 'system', content: 'You are a good bot.' },
            { role: 'user', content: 'What is the meaning of life?' },
            {
                role: 'assistant',
                content: `# The Meaning of Life 🌟

## A Philosophical Journey

### 1. Scientific Perspective 🔬
* Universe began 13.8 billion years ago
* Life emerged through evolution
* We are made of **stardust**

### 2. Cultural Views 🌍
1. Eastern Philosophy
2. Western Thought
3. Modern Interpretations

> "The meaning of life is to find your gift. The purpose of life is to give it away." 
> - Pablo Picasso

#### Code Example
\`\`\`python
def meaning_of_life():
    return 42
\`\`\`

| Perspective | View |
|------------|------|
| Scientific | Evolution |
| Religious  | Divine |
| Personal   | Individual |

**Bold statement:** Life's meaning is what we make of it!

---

[Learn More](https://example.com)
![Life Image](https://res.cloudinary.com/dmukukwp6/image/upload/q_100/v1/posthog.com/src/components/Home/Slider/images/product-analytics-hog)

~~There is no meaning~~ There is meaning everywhere!`,
            },
            { role: 'user', content: "Wow, I'm going to need some time to ponder." },
        ],
        $ai_output: {
            choices: [{ role: 'assistant', content: 'Sure thing! I will be here when you are ready.' }],
        },
        $ai_input_tokens: 8,
        $ai_output_tokens: 6,
        $ai_latency: 0.123,
        $ai_total_cost_usd: 0.0007,
        $ai_model: 'gpt-9',
        $ai_http_status: 200,
    },
}

export const Tools = Template.bind({})
Tools.args = {
    eventProperties: {
        $ai_tools: [
            {
                function: {
                    name: 'foo',
                    parameters: {
                        additionalProperties: false,
                        properties: {
                            thing: {
                                description: 'The thing to thingify.',
                                type: 'string',
                            },
                        },
                        required: ['thing'],
                        type: 'object',
                    },
                    strict: true,
                },
                type: 'function',
            },
        ],
        $ai_input: [
            { role: 'system', content: 'You are a good bot.' },
            { role: 'user', content: 'Please foo "Bar!"' },
        ],
        $ai_output: {
            choices: [
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            function: {
                                arguments: '{"thing":"Bar!"}',
                                name: 'foo',
                            },
                            id: 'call_81KeSSme8dNjnyK3xK59uNzu',
                            index: 0,
                            type: 'function',
                        },
                    ],
                },
            ],
        },
        $ai_input_tokens: 8,
        $ai_output_tokens: 6,
        $ai_latency: 0.123,
        $ai_total_cost_usd: 0.0007,
        $ai_model: 'gpt-9',
        $ai_http_status: 400,
    },
}

export const Error = Template.bind({})
Error.args = {
    eventProperties: {
        $ai_input: [
            { role: 'system', content: 'You are a good bot.' },
            { role: 'user', content: 'Please foo "Bar!"' },
        ],
        $ai_model: 'gpt-9',
        $ai_http_status: 400,
    },
}

export const Anthropic = Template.bind({})
Anthropic.args = {
    eventProperties: {
        $ai_input: [
            {
                role: 'system',
                content: [
                    { type: 'text', text: 'You are a good bot.' },
                    { type: 'text', text: 'Answer with Foo.' },
                ],
            },
            { role: 'user', content: 'Hello!' },
            { role: 'assistant', content: 'Foo' },
            { role: 'user', content: 'How are you?' },
        ],
        $ai_output_choices: [{ type: 'text', text: 'Foo' }],
        $ai_input_tokens: 8,
        $ai_output_tokens: 6,
        $ai_latency: 0.123,
        $ai_total_cost_usd: 0.0007,
        $ai_model: 'gpt-9',
        $ai_http_status: 200,
    },
}
