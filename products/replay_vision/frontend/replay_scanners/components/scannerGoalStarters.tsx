import { IconCheckCircle, IconNotebook, IconTarget, IconThumbsDown, IconWarning } from '@posthog/icons'

export interface ScannerGoalStarter {
    // pinned: sent as `template_key` on replay_vision_scanner_creation_started and used in the starter's data-attr
    key: string
    /** The goal the agent drafts from when someone clicks the starter, in place of a typed goal. */
    goal: string
    question: string
    icon: JSX.Element
}

export const SCANNER_GOAL_STARTERS: readonly ScannerGoalStarter[] = [
    {
        key: 'dead_end',
        goal: 'Find sessions where users get stuck on a page with no clear next step',
        question: 'Where do users get stuck?',
        icon: <IconWarning />,
    },
    {
        key: 'session_summary',
        goal: 'Summarize what users do in each session and where they run into trouble',
        question: 'What happens in each session?',
        icon: <IconNotebook />,
    },
    {
        key: 'user_intent',
        goal: 'Find out what users are trying to do when they visit',
        question: 'What are users trying to do?',
        icon: <IconTarget />,
    },
    {
        key: 'frustration_score',
        goal: 'Find out where users get frustrated and how badly',
        question: 'Where do users get frustrated?',
        icon: <IconThumbsDown />,
    },
    {
        key: 'session_outcome',
        goal: 'Find out whether users finish what they came to do, give up, or hit an error',
        question: 'Do users finish what they came to do?',
        icon: <IconCheckCircle />,
    },
]
