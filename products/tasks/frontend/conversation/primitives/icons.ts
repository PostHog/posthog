import {
    IconAI,
    IconArrowLeft,
    IconArrowRight,
    IconArrowRightDown,
    IconArrowUpRight,
    IconBolt,
    IconBrain,
    IconBug,
    IconChat,
    IconCheck,
    IconCheckCircle,
    IconChevronDown,
    IconChevronRight,
    IconChip,
    IconCircleDashed,
    IconClock,
    IconCloud,
    IconCode,
    IconCollapse,
    IconCommit,
    type IconComponent,
    IconCopy,
    IconDashboard,
    IconDatabase,
    IconDocument,
    IconExpand,
    IconExternal,
    IconFlag,
    IconFlask,
    IconFolder,
    IconGitBranch,
    IconGlobe,
    type IconProps,
    IconList,
    IconMinus,
    IconNotebook,
    IconPause,
    IconPencil,
    IconPlug,
    IconPlus,
    IconPullRequest,
    IconQuestion,
    IconRefresh,
    IconSearch,
    IconSparkles,
    IconSpinner,
    IconStopFilled,
    IconTerminal,
    IconTrash,
    IconTrends,
    IconUpload,
    IconVideoCamera,
    IconWarning,
    IconWrench,
    IconX,
} from '@posthog/icons'

/**
 * Maps the Phosphor icon names referenced across the conversation renderers to
 * their `@posthog/icons` equivalents, so ported files can write
 * `ICONS.PencilSimple` instead of importing Phosphor (which does not exist
 * here).
 *
 * NOTE: `@posthog/icons` icons do not take a `size` prop — set size via
 * `style={{ fontSize }}` or a `text-*` / `w-*`/`h-*` class.
 */
export type Icon = IconComponent<IconProps>
export type { IconProps }

export const ICONS: Record<string, Icon> = {
    // Arrows & motion
    ArrowDown: IconArrowRightDown, // no plain down arrow in this version
    ArrowUp: IconArrowUpRight, // no plain up arrow in this version
    ArrowLeft: IconArrowLeft,
    ArrowRight: IconArrowRight,
    ArrowLineDown: IconArrowRightDown,
    ArrowsClockwise: IconRefresh,
    ArrowsLeftRight: IconArrowRightDown,
    ArrowsInSimple: IconCollapse,
    ArrowsOutSimple: IconExpand,
    ArrowSquareOut: IconExternal,

    // Carets / chevrons (CaretUp reuses ChevronDown — rotate via class)
    CaretDown: IconChevronDown,
    CaretRight: IconChevronRight,
    CaretUp: IconChevronDown,

    // Status & feedback
    Check: IconCheck,
    CheckCircle: IconCheckCircle,
    Circle: IconCircleDashed, // no plain IconCircle in this version
    CircleNotch: IconSpinner,
    Spinner: IconSpinner,
    Clock: IconClock,
    Warning: IconWarning,
    Stop: IconStopFilled,
    X: IconX,
    XCircle: IconX,
    Question: IconQuestion,

    // Thinking / agent
    Brain: IconBrain,
    Robot: IconAI, // no IconRobot in this version
    Sparkle: IconSparkles,

    // Tools & actions
    Command: IconBolt,
    Lightning: IconBolt,
    Copy: IconCopy,
    PencilSimple: IconPencil,
    Plus: IconPlus,
    Minus: IconMinus,
    Trash: IconTrash,
    Wrench: IconWrench,
    MagnifyingGlass: IconSearch,
    Terminal: IconTerminal,
    Pause: IconPause,

    // Files & folders
    File: IconDocument,
    FileText: IconDocument,
    FileArrowUp: IconUpload,
    Folder: IconFolder,
    ClipboardText: IconNotebook,

    // Communication / network
    ChatCircle: IconChat,
    SlackLogo: IconChat, // no slack icon — use chat
    Globe: IconGlobe,
    Cloud: IconCloud,
    CloudArrowUp: IconCloud,

    // Git
    GitBranch: IconGitBranch,
    GitCommit: IconCommit,
    GitDiff: IconList, // no diff icon — use list
    GitPullRequest: IconPullRequest,

    // Resources (SessionResourcesBar)
    Bug: IconBug,
    ChartLine: IconTrends,
    Code: IconCode,
    Database: IconDatabase,
    Flag: IconFlag,
    Flask: IconFlask,
    Gauge: IconDashboard, // no gauge icon — use dashboard
    Plug: IconPlug,
    Table: IconList, // no table icon — use list
    Video: IconVideoCamera,
    Cpu: IconChip,
}

// Convenience named re-exports — the icons referenced most often by the
// renderers, so call sites can `import { IconBrain } from '.../primitives/icons'`
// without reaching back into `@posthog/icons`.
export {
    IconAI,
    IconArrowRightDown,
    IconBolt,
    IconBrain,
    IconChat,
    IconCheck,
    IconCheckCircle,
    IconChevronDown,
    IconChevronRight,
    IconCircleDashed,
    IconClock,
    IconCloud,
    IconCollapse,
    IconCopy,
    IconDocument,
    IconExpand,
    IconExternal,
    IconFolder,
    IconGitBranch,
    IconGlobe,
    IconList,
    IconMinus,
    IconPencil,
    IconPlus,
    IconPullRequest,
    IconQuestion,
    IconRefresh,
    IconSearch,
    IconSpinner,
    IconTerminal,
    IconTrash,
    IconWarning,
    IconWrench,
    IconX,
}
