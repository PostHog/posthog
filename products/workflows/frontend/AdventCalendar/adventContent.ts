import type { HoggiePngModule } from 'lib/brand/hoggies'

import { ADVENT_FOUNDERS } from './adventFounders'

export const ADVENT_LAST_DAY = 24
export const ADVENT_YEAR = 2026

export interface AdventReward {
    id: string
    name: string
    image: HoggiePngModule
    line?: string
    isPortrait?: boolean
}

export interface AdventOption {
    id: string
    label: string
    reply: string
    reward?: AdventReward
}

export interface AdventQuestion {
    topic: string
    prompt: string
    options: AdventOption[]
}

export type AdventTipKind = 'Did you know?' | 'Workflows tip' | 'From the handbook' | 'Just for fun'

export interface AdventTip {
    kind: AdventTipKind
    text: string
    link?: { label: string; url: string }
}

export const ADVENT_QUESTIONS: Record<number, AdventQuestion> = {
    2: {
        topic: 'Favorite founder',
        prompt: 'Who is your favorite founder?',
        options: [
            { id: 'james', label: 'James', reply: 'Noted. Tim will hear about this.', reward: ADVENT_FOUNDERS.james },
            { id: 'tim', label: 'Tim', reply: 'Noted. James will hear about this.', reward: ADVENT_FOUNDERS.tim },
        ],
    },
    5: {
        topic: 'Pineapple on pizza',
        prompt: 'Pineapple on pizza?',
        options: [
            { id: 'yes', label: 'Yes', reply: 'A brave choice. The chef has been told.' },
            { id: 'no', label: 'No', reply: 'A safe choice. You still get a hedgehog.' },
        ],
    },
    10: {
        topic: 'Tabs or spaces',
        prompt: 'Tabs or spaces?',
        options: [
            { id: 'tabs', label: 'Tabs', reply: 'A strong opinion. The formatter will decide anyway.' },
            { id: 'spaces', label: 'Spaces', reply: 'A strong opinion. The formatter will decide anyway.' },
        ],
    },
    13: {
        topic: 'Dark or light mode',
        prompt: 'Dark mode or light mode?',
        options: [
            { id: 'dark', label: 'Dark mode', reply: 'Hedgehogs are nocturnal too.' },
            { id: 'light', label: 'Light mode', reply: 'Bright and early.' },
        ],
    },
    18: {
        topic: 'Ship on a Friday',
        prompt: 'It is Friday. Do you ship?',
        options: [
            { id: 'yes', label: 'Ship it', reply: 'Brave. The hedgehog is with you.' },
            { id: 'no', label: 'Wait for Monday', reply: 'Sensible. The hedgehog approves.' },
        ],
    },
    21: {
        topic: 'Coffee or tea',
        prompt: 'Coffee or tea?',
        options: [
            { id: 'coffee', label: 'Coffee', reply: 'Brewing. The deploy can wait one cup.' },
            { id: 'tea', label: 'Tea', reply: 'Kettle is on. Take your time.' },
        ],
    },
}

export const ADVENT_QUESTION_DAYS = Object.keys(ADVENT_QUESTIONS).map(Number)

export function adventQuestionBefore(day: number): number | null {
    return ADVENT_QUESTION_DAYS.find((questionDay) => day === questionDay + 1 || day === questionDay + 2) ?? null
}

const STORY = { label: 'Read the story', url: 'https://posthog.com/handbook/story' }
const CULTURE = { label: 'Read the handbook page', url: 'https://posthog.com/handbook/company/culture' }
const WORKFLOWS_DOCS = { label: 'Workflows docs', url: 'https://posthog.com/docs/workflows' }

export const ADVENT_TIPS: Record<number, AdventTip> = {
    1: { kind: 'Did you know?', text: 'PostHog was founded by James and Tim on January 23, 2020.', link: STORY },
    2: {
        kind: 'Just for fun',
        text: 'This question has no wrong answer. Both James and Tim appear in the company story.',
    },
    3: {
        kind: 'Workflows tip',
        text: 'A delay step makes a workflow wait for a set time before it moves to the next step.',
        link: WORKFLOWS_DOCS,
    },
    4: {
        kind: 'From the handbook',
        text: 'PostHog has no internal meetings on Tuesdays and Thursdays.',
        link: CULTURE,
    },
    5: {
        kind: 'Did you know?',
        text: 'Team pages on posthog.com have a pineapple on pizza section.',
        link: { label: 'See the teams', url: 'https://posthog.com/teams' },
    },
    6: {
        kind: 'Did you know?',
        text: 'PostHog was the sixth idea of its founders. They changed direction almost once a month for half a year.',
        link: STORY,
    },
    7: {
        kind: 'Workflows tip',
        text: 'Workflows can record email sends, opens, and clicks as events. You can build an insight on any email a workflow sends.',
        link: WORKFLOWS_DOCS,
    },
    8: {
        kind: 'From the handbook',
        text: 'The handbook is public, and anyone can propose an edit.',
        link: { label: 'Open the handbook', url: 'https://posthog.com/handbook' },
    },
    9: {
        kind: 'Workflows tip',
        text: 'You can send transactional emails from your code with PostHog. Sends, opens, and clicks arrive as events, with no extra tracking to set up.',
        link: {
            label: 'Transactional emails docs',
            url: 'https://posthog.com/docs/workflows/transactional-emails',
        },
    },
    10: { kind: 'Just for fun', text: 'Whatever you picked, the formatter has the last word.' },
    11: {
        kind: 'Did you know?',
        text: 'The first version launched on Hacker News four weeks after the first line of code.',
        link: STORY,
    },
    12: {
        kind: 'Workflows tip',
        text: 'A conditional branch sends different people down different paths based on their properties or events. A cohort branch splits people at random by percentage.',
        link: WORKFLOWS_DOCS,
    },
    13: {
        kind: 'From the handbook',
        text: 'The team is fully remote and spread across more than 20 countries.',
        link: CULTURE,
    },
    14: {
        kind: 'Workflows tip',
        text: 'Any real-time destination in PostHog can be a step in a workflow.',
        link: WORKFLOWS_DOCS,
    },
    15: { kind: 'Just for fun', text: 'A group of hedgehogs is called an array.' },
    16: {
        kind: 'Did you know?',
        text: "PostHog's blog has a post on how teams use PostHog to build great products, from pirate metrics dashboards to kill-switch feature flags.",
        link: { label: 'Read the post', url: 'https://posthog.com/blog/using-posthog' },
    },
    17: {
        kind: 'Workflows tip',
        text: 'Reusable message templates live in the content library. You can personalize them with person properties.',
        link: { label: 'Content library docs', url: 'https://posthog.com/docs/workflows/library' },
    },
    18: { kind: 'From the handbook', text: 'The handbook on shipping: "If given a choice, go live."', link: CULTURE },
    19: {
        kind: 'Workflows tip',
        text: 'You can create, test, and publish a workflow from any MCP client.',
        link: { label: 'MCP docs', url: 'https://posthog.com/docs/workflows/surfaces/mcp' },
    },
    20: { kind: 'Did you know?', text: 'A baby hedgehog is called a hoglet.' },
    21: {
        kind: 'From the handbook',
        text: 'PostHog writes things down. Most communication happens in public issues and pull requests.',
        link: CULTURE,
    },
    22: {
        kind: 'Workflows tip',
        text: 'Message categories and recipient preferences decide who gets a message. Bounces fill the suppression list.',
        link: { label: 'Opt-out docs', url: 'https://posthog.com/docs/workflows/opt-outs' },
    },
    23: { kind: 'Just for fun', text: 'Many hedgehog species hibernate through the winter.' },
    24: {
        kind: 'From the handbook',
        text: 'The roadmap is open for anyone to see. It lists what PostHog is building and which features are in beta.',
        link: { label: 'Open the roadmap', url: 'https://posthog.com/roadmap' },
    },
}
