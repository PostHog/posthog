import { AssistantFailureMessage } from '../messages/AssistantFailureMessage'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { MessageTemplate } from '../messages/MessageTemplate'
import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import { Activity } from './ActivityPrimitives'
import { ThreadView } from './ThreadView'
import { ToolCallCard } from './tool/ToolCallCard'

// Radix-style compound for the agent run thread. `Thread.Root` is the prepackaged, virtualized presenter
// that reads the bound `runStreamLogic` and dispatches every thread item; the leaf atoms below are the
// same presentational building blocks it uses, exposed so a surface can assemble a bespoke thread (e.g. a
// static transcript, an embedded preview) from plain props without the streaming machinery. The atoms are
// runtime-agnostic and take plain props — they know nothing about langgraph vs sandbox or the conversation.
export const Thread = Object.assign(ThreadView, {
    /** The full streamed thread: virtualized rows + run-context header + thinking/PR footer. */
    Root: ThreadView,
    /** Human/assistant message bubble wrapper. */
    Message: MessageTemplate,
    /** Markdown body renderer (used inside messages and activity details). */
    Markdown: MarkdownMessage,
    /** Extended-thinking / reasoning line (a bubble-free Activity card). */
    Reasoning: ReasoningAnswer,
    /** Error / crash message card. */
    Failure: AssistantFailureMessage,
    /** Progress / status activity card. */
    Activity: Activity,
    /** Tool-call card — resolves its renderer through the tool registry. */
    ToolCall: ToolCallCard,
})
