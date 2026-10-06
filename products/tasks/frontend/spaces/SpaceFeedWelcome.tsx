import { useActions, useValues } from 'kea'

import {
    IconBug,
    IconCode,
    IconDashboard,
    IconFlask,
    IconMessage,
    IconPiggyBank,
    IconTrends,
    IconWrench,
} from '@posthog/icons'
import {
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { spaceSceneLogic } from './spaceSceneLogic'

interface SpaceSuggestion {
    label: string
    description: string
    prompt: string
    Icon: typeof IconBug
}

const SPACE_SUGGESTIONS: SpaceSuggestion[] = [
    {
        label: 'Debug a user issue',
        description: 'Trace a specific user’s events, replays, and errors',
        Icon: IconBug,
        prompt: 'Help me debug an issue a specific user is hitting. Pull their recent events, session replays, and errors, then figure out what went wrong. Build a canvas that explains what you found and the evidence behind it.\n\n\nUser input:\n- Describe the user issue:\n- User identifier (distinct ID, email address, etc):',
    },
    {
        label: 'Run a feature analysis',
        description: 'Adoption, engagement, and retention of a feature',
        Icon: IconTrends,
        prompt: 'Analyze how a feature is performing: adoption, engagement, and retention of users who use it vs. those who don’t. Build a canvas that explains what you found, with the charts behind it.\n\n\nUser input:\n- Feature to analyze:\n- Time period (optional):',
    },
    {
        label: 'Understand revenue patterns',
        description: 'Trends over time, by plan, and by cohort',
        Icon: IconPiggyBank,
        prompt: 'Analyze our revenue trends. Break it down over time, by plan, and by cohort, and call out notable changes and likely drivers. Build a canvas that explains what you found, with the charts behind it.\n\n\nUser input:\n- What revenue question are you trying to answer:\n- Time period (optional):',
    },
    {
        label: 'Build a canvas',
        description: 'Research a question and explain the answer',
        Icon: IconDashboard,
        prompt: 'Research a question about our product, then build a canvas that explains the answer. Include the charts that show it and short written context for what they mean.\n\n\nUser input:\n- What should the canvas explain:\n- Time period (optional):',
    },
    {
        label: 'Summarize user & agent feedback',
        description: 'Common themes across recent feedback',
        Icon: IconMessage,
        prompt: 'Summarize recent user and support/agent feedback. Surface the common themes, complaints, and requests. Build a canvas that explains the themes, with examples behind each one.\n\n\nUser input:\n- Feedback source or topic to focus on:\n- Time period (optional):',
    },
    {
        label: 'Interpret experiment results',
        description: 'Significance and what to do next',
        Icon: IconFlask,
        prompt: 'Interpret the results of an experiment. Explain what the metrics show, whether it’s significant, and what to do next. Build a canvas that explains the result and your recommendation.\n\n\nUser input:\n- Experiment name or key:\n- What decision are you trying to make (optional):',
    },
    {
        label: 'Fix a bug',
        description: 'Track down and fix a problem in the code',
        Icon: IconWrench,
        prompt: 'Help me fix a bug. Track down the root cause in the code and implement a fix. Open a PR if appropriate.\n\n\nUser input:\n- Describe the bug / what’s going wrong:\n- Steps to reproduce (optional):\n- Where it happens (file, page, area, optional):',
    },
    {
        label: 'Build a new feature',
        description: 'Design and implement something new',
        Icon: IconCode,
        prompt: 'Help me build a new feature. Propose an approach, then implement it. Open a PR if appropriate.\n\n\nUser input:\n- Describe the feature you want:\n- Any constraints or requirements (optional):',
    },
]

export function SpaceFeedWelcome({ id }: { id: string }): JSX.Element {
    const { space } = useValues(spaceSceneLogic({ id }))
    const { applySuggestion } = useActions(spaceSceneLogic({ id }))
    const title =
        space?.system_role === 'personal'
            ? 'Welcome to your personal space'
            : space
              ? `Welcome to ${space.name}`
              : 'Welcome'

    return (
        <Empty className="mt-4 gap-6" data-attr="today-space-welcome">
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                <EmptyDescription>
                    Start a session from the composer above, or pick a suggestion to fill it in.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="w-full max-w-none items-stretch gap-2">
                <Text size="sm" weight="medium" variant="muted" className="px-1 text-left">
                    Suggestions
                </Text>
                <div className="grid grid-cols-1 gap-2 @lg/main-content:grid-cols-2">
                    {SPACE_SUGGESTIONS.map(({ label, description, prompt, Icon }) => (
                        <Item
                            key={label}
                            variant="outline"
                            size="sm"
                            className="flex-nowrap text-left hover:bg-fill-hover"
                            render={
                                <button
                                    type="button"
                                    onClick={() => applySuggestion(prompt)}
                                    data-attr="today-space-suggestion"
                                />
                            }
                        >
                            <ItemMedia variant="icon">
                                <Icon />
                            </ItemMedia>
                            <ItemContent className="min-w-0">
                                <ItemTitle className="w-full truncate">{label}</ItemTitle>
                                <ItemDescription className="line-clamp-1">{description}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ))}
                </div>
            </EmptyContent>
        </Empty>
    )
}
