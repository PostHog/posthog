import { IconBook, IconCode } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { productUrls } from '~/products'

import { type SuggestionGroup } from './Suggestions'

// Default, overridable suggestion content for the Suggestions primitive. The "Coding" group leads (this
// surface drives an agent that writes code), followed by PostHog's analytics categories. Pass your own
// array to override.
export const DEFAULT_SUGGESTIONS_DATA: readonly SuggestionGroup[] = [
    {
        label: 'Coding',
        icon: <IconCode />,
        suggestions: [
            {
                content: 'Instrument an event/property',
                requiresUserInput: true,
            },
            {
                content: 'Fix a bug for me',
                requiresUserInput: true,
            },
            {
                content: 'Research how my codebase works',
            },
        ],
        tooltip: 'PostHog AI can write code in your repository — instrument events, fix bugs, and explore code.',
    },
    {
        label: 'Product analytics',
        icon: iconForType('product_analytics'),
        suggestions: [
            {
                content: 'Create a funnel of the Pirate Metrics (AARRR)',
            },
            {
                content: 'What are the most popular pages or screens?',
            },
            {
                content: 'What is the retention in the last two weeks?',
            },
            {
                content: 'What are the top referring domains?',
            },
            {
                content: 'Calculate a conversion rate for <events or actions>…',
                requiresUserInput: true,
            },
        ],
        tooltip: 'PostHog AI can generate insights from natural language and tweak existing ones.',
    },
    {
        label: 'SQL',
        icon: iconForType('insight/hog'),
        suggestions: [
            {
                content: 'Write an SQL query to…',
                requiresUserInput: true,
            },
        ],
        url: urls.sqlEditor(),
        tooltip: 'PostHog AI can generate SQL queries for your PostHog data, both analytics and the data warehouse.',
    },
    {
        label: 'Session replay',
        icon: iconForType('session_replay'),
        suggestions: [
            {
                content: 'Find recordings for…',
                requiresUserInput: true,
            },
        ],
        url: productUrls.replay(),
        tooltip: 'PostHog AI can find session recordings for you.',
    },
    {
        label: 'SDK setup',
        icon: iconForType('sql_editor'),
        suggestions: [
            {
                content: 'How can I set up the session replay in <a framework or language>…',
                requiresUserInput: true,
            },
            {
                content: 'How can I set up the feature flags in…',
                requiresUserInput: true,
            },
            {
                content: 'How can I set up the experiments in…',
                requiresUserInput: true,
            },
            {
                content: 'How can I set up the data warehouse in…',
                requiresUserInput: true,
            },
            {
                content: 'How can I set up the error tracking in…',
                requiresUserInput: true,
            },
            {
                content: 'How can I set up AI observability in…',
                requiresUserInput: true,
            },
            {
                content: 'How can I set up the product analytics in…',
                requiresUserInput: true,
            },
        ],
        tooltip: 'PostHog AI can help you set up PostHog SDKs in your stack.',
    },
    {
        label: 'Feature flags',
        icon: iconForType('feature_flag'),
        url: urls.featureFlags(),
        suggestions: [
            {
                content: 'Create a flag to gradually roll out…',
                requiresUserInput: true,
            },
            {
                content: 'Create a flag that starts at 10% rollout for…',
                requiresUserInput: true,
            },
            {
                content: 'Create a multivariate flag for…',
                requiresUserInput: true,
            },
            {
                content: 'Create a beta testing flag for…',
                requiresUserInput: true,
            },
            {
                content: 'Audit my feature flags for issues',
            },
        ],
    },
    {
        label: 'Experiments',
        icon: iconForType('experiment'),
        url: urls.experiments(),
        suggestions: [
            {
                content: 'Create an experiment to test…',
                requiresUserInput: true,
            },
            {
                content: 'Set up an A/B test with a 70/30 split between control and test for…',
                requiresUserInput: true,
            },
            {
                content: 'Check if my running experiments are set up correctly',
            },
        ],
    },
    {
        label: 'Surveys',
        icon: iconForType('survey'),
        suggestions: [
            {
                content: 'Create a survey to collect NPS responses from users',
            },
            {
                content: 'Create a survey to collect CSAT responses from users',
            },
            {
                content: 'Create a survey to measure product market fit',
            },
            {
                content: 'Analyze survey responses to prioritize key features our users are interested in',
            },
        ],
        url: urls.surveys(),
        tooltip: 'PostHog AI can help you create surveys to collect feedback from your users.',
    },
    {
        label: 'Docs',
        icon: <IconBook />,
        suggestions: [
            {
                content: 'How can I create a feature flag?',
            },
            {
                content: 'Where do I watch session replays?',
            },
            {
                content: 'Help me set up an experiment',
            },
            {
                content: 'Explain autocapture',
            },
            {
                content: 'How can I capture an exception?',
            },
        ],
        tooltip: 'PostHog AI has access to PostHog docs and can help you get the most out of PostHog.',
    },
]
