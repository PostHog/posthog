// Tier 2 — compound primitives & presenters: the broad presentational bucket for custom layouts and
// bespoke threads. The Composer compound, the Thread compound + atoms, the prepackaged `ThreadView`,
// message presenters, the shared `RunLogSkeleton` loader, activity primitives, and the
// permission/question/resource surfaces. Use when the prepackaged `ReadonlyRunSurface` (Tier 1,
// ./readableRun) doesn't fit and you need to compose the pieces yourself — e.g. a compact inline thread via
// `Thread.*` atoms.
//
// (This is intentionally the wide presentational module; it can be subdivided later — e.g. thread.ts /
// composer.ts — if a consumer needs finer code-splitting.)
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../components/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { Composer } from '../components/composer/Composer'
export type {
    ComposerRootProps,
    ComposerFrameProps,
    ComposerTextareaProps,
    ComposerSubmitProps,
} from '../components/composer/Composer'

// Welcome header (logomark + headline + subheadline) and its overridable default headlines.
export { Welcome } from '../components/welcome/Welcome'
export type { WelcomeProps } from '../components/welcome/Welcome'
export { DEFAULT_HEADLINES, pickHeadline } from '../components/welcome/welcomeDefaults'

// Suggestions compound (the "Try PostHog AI for…" button row + in-input dropdown) and its default content.
export { Suggestions } from '../components/suggestions/Suggestions'
export type {
    SuggestionItem,
    SuggestionGroup,
    SuggestionsRootProps,
    SuggestionsButtonsProps,
    SuggestionsDropdownProps,
} from '../components/suggestions/Suggestions'
export { DEFAULT_SUGGESTIONS_DATA } from '../components/suggestions/suggestionsDefaults'

// `Thread` is the Radix-style compound (Root + Message/Markdown/Reasoning/Failure/Activity/ToolCall
// atoms); `ThreadView` is the prepackaged virtualized presenter (also `Thread.Root`).
export { Thread } from '../components/Thread'
export { ThreadView } from '../components/ThreadView'
export { MessageTemplate } from '../messages/MessageTemplate'
export { MarkdownMessage } from '../messages/MarkdownMessage'
export { ReasoningAnswer } from '../messages/ReasoningAnswer'
export type { ReasoningAnswerProps } from '../messages/ReasoningAnswer'
export { AssistantFailureMessage } from '../messages/AssistantFailureMessage'
export { RunLogSkeleton } from '../components/RunLogSkeleton'
export { QueuedMessageList } from '../components/QueuedMessageList'
export type { QueuedMessageListProps } from '../components/QueuedMessageList'

export {
    Activity,
    ActivityDetails,
    ActivityHeader,
    ActivityStatusIcon,
    ActivitySubsteps,
    ActivityToggleSection,
    ShimmeringContent,
} from '../components/ActivityPrimitives'
export type { ActivityStatus } from '../components/ActivityPrimitives'
export { RunActivity } from '../components/RunActivity'
export { RunAlertActivity } from '../components/RunAlertActivity'

export { PermissionInput } from '../components/PermissionInput'
export { QuestionInput } from '../components/QuestionInput'
export { ResourcesBar } from '../components/ResourcesBar'
export { ContextUsageBar } from '../components/ContextUsageBar'
export { QuestionField, MultiFieldQuestion, isFieldValid } from '../components/QuestionField'
export { OptionSelector } from '../components/OptionSelector'
export type { Option } from '../components/OptionSelector'
