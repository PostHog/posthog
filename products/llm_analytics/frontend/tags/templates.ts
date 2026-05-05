import { TaggerConfig } from './types'

export interface TaggerTemplate {
    key: string
    name: string
    description: string
    icon: 'tag' | 'message-circle' | 'shield' | 'zap' | 'users'
    tagger_config: TaggerConfig
}

export const defaultTaggerTemplates: readonly TaggerTemplate[] = [
    {
        key: 'topic',
        name: 'Topic tags',
        description: 'Tag each generation with the topics or subject areas it covers',
        icon: 'tag',
        tagger_config: {
            prompt: 'Tag this AI generation with the topics or subject areas it covers. Select all that substantively apply.',
            tags: [
                { name: 'technical-support', description: 'Troubleshooting, debugging, or fixing technical issues' },
                { name: 'how-to', description: 'Step-by-step instructions or tutorials' },
                { name: 'general-knowledge', description: 'Factual questions or explanations about concepts' },
                { name: 'creative', description: 'Creative writing, brainstorming, or ideation' },
                { name: 'data-analysis', description: 'Working with data, charts, queries, or analytics' },
                { name: 'code-generation', description: 'Writing or modifying code' },
            ],
            min_tags: 0,
            max_tags: null,
        },
    },
    {
        key: 'intent',
        name: 'User intent',
        description: 'Tag what the user is trying to accomplish',
        icon: 'message-circle',
        tagger_config: {
            prompt: "Tag the primary intent behind the user's message in this generation. What is the user trying to accomplish?",
            tags: [
                { name: 'question', description: 'Asking a question or seeking information' },
                { name: 'task', description: 'Requesting the AI to perform a specific task' },
                { name: 'conversation', description: 'Casual conversation or chat' },
                { name: 'feedback', description: 'Providing feedback or corrections to the AI' },
                { name: 'follow-up', description: 'Following up on a previous response or asking for clarification' },
            ],
            min_tags: 0,
            max_tags: null,
        },
    },
    {
        key: 'safety',
        name: 'Safety flags',
        description: 'Flag generations that may contain sensitive or risky content',
        icon: 'shield',
        tagger_config: {
            prompt: 'Review this AI generation and flag any safety concerns. Only select tags that clearly apply — most generations should have no flags.',
            tags: [
                {
                    name: 'pii',
                    description: 'Contains personally identifiable information (names, emails, addresses, etc.)',
                },
                { name: 'medical-advice', description: 'Provides specific medical or health advice' },
                { name: 'financial-advice', description: 'Provides specific financial or investment advice' },
                { name: 'legal-advice', description: 'Provides specific legal advice' },
                { name: 'controversial', description: 'Discusses politically sensitive or controversial topics' },
            ],
            min_tags: 0,
            max_tags: null,
        },
    },
    {
        key: 'complexity',
        name: 'Response complexity',
        description: 'Tag the complexity level of each AI response',
        icon: 'zap',
        tagger_config: {
            prompt: "Assess the complexity of the AI's response. Select the single best-fitting complexity level.",
            tags: [
                { name: 'simple', description: 'Short, straightforward answer with no technical depth' },
                { name: 'moderate', description: 'Detailed explanation requiring some domain knowledge' },
                { name: 'complex', description: 'In-depth technical or analytical response with multiple parts' },
                { name: 'expert', description: 'Highly specialized response requiring deep expertise' },
            ],
            min_tags: 0,
            max_tags: null,
        },
    },
    {
        key: 'sentiment',
        name: 'User sentiment',
        description: 'Tag the emotional tone of the user in each conversation',
        icon: 'users',
        tagger_config: {
            prompt: "Analyze the emotional tone of the user's messages (not the AI's response) in this generation. What sentiment is the user expressing?",
            tags: [
                { name: 'satisfied', description: 'User seems happy or satisfied with the interaction' },
                { name: 'neutral', description: 'User shows no strong emotion' },
                { name: 'frustrated', description: 'User seems frustrated, confused, or dissatisfied' },
                { name: 'urgent', description: 'User seems to need help urgently or is under time pressure' },
            ],
            min_tags: 0,
            max_tags: null,
        },
    },
] as const

export type TaggerTemplateKey = (typeof defaultTaggerTemplates)[number]['key']
