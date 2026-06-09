# Conversation renderer — porting CONTRACT

Single source of truth for porting PostHog Code's conversation / session-log
renderer into `posthog/posthog`. Every downstream agent MUST follow the module
tree, export names, and signatures below so files never collide or guess.

All paths are absolute under:
`/tmp/workspace/repos/posthog/posthog/products/tasks/frontend/conversation/`
(referred to below as `<root>/`).

Reference source root (read the named file before porting):
`/tmp/workspace/repos/code/apps/code/src/renderer/features/sessions/components/`
(referred to below as `<ref>/`; `<ref-su>/` = `<ref>/session-update/`).

## Hard rules (apply to EVERY file)

- This is `posthog/posthog`, NOT the Electron app. NEVER import from:
  `@radix-ui/*`, `@phosphor-icons/*`, `@pierre/*`, `@codemirror/*`, `@lezer/*`,
  `framer-motion`, `@agentclientprotocol/sdk`, `react-markdown`, `zustand`,
  `@features/*`, `@components/*`, `@shared/*`, `@utils/*`, `@posthog/agent`,
  `@posthog/quill`. None exist here.
- PostHog-native replacements:
  - Markdown → `LemonMarkdown` from `lib/lemon-ui/LemonMarkdown`
    (`<LemonMarkdown>{string}</LemonMarkdown>`; props: `lowKeyHeadings`,
    `disableDocsRedirect`, `className`, `wrapCode`).
  - Code / syntax highlight → `CodeSnippet`, `Language`, `getLanguage` from
    `lib/components/CodeSnippet`.
  - Collapse → `LemonCollapse` from `@posthog/lemon-ui`.
  - Buttons / tags / spinner / tooltip → `LemonButton`, `LemonTag`, `Spinner`,
    `Tooltip` from `@posthog/lemon-ui`.
  - Icons → `@posthog/icons` directly, OR via the shared map in
    `<root>/primitives/icons.ts` (see below).
- Layout: plain `<div>` + Tailwind utilities (`flex`, `gap-2`, `items-center`,
  `pl-3`, …). Match the reference's visual spacing.
- TypeScript: explicit return types on every exported function/component
  (`JSX.Element | null`). No `any`. Annotate prop interfaces.
- American English; Sentence casing for UI labels (e.g. "Commit & push").
- Do NOT run pnpm/tsc/tests.

## READ-ONLY transcript

This renderer displays a **finished, read-only transcript** reconstructed from
S3 logs (or replayed SSE). There is:

- NO input composer / send box.
- NO live git, tRPC, MCP iframe host, or "open in editor" links — render those
  affordances as **static / disabled** (plain text or a disabled `LemonButton`),
  never wired to a backend.
- NO zustand store. The reference reads from `sessionStore`; here, pass data in
  as plain props/args (events array, queued messages, etc.).
- NO virtualization dependency (`@pierre/diffs`, `VirtualizedList`): render a
  plain scrollable list. A virtualized list may be added later but is not
  required and must not pull native worker deps.

---

## FOUNDATION — already written (this task)

### `<root>/acp-types.ts`

Vendored, self-contained ACP / JSON-RPC / session types. NO external imports.
Ports: `@agentclientprotocol/sdk` schema + `<shared>/types/session-events.ts` +
`<ref>/../types.ts`.

Exports:
- Interfaces: `JsonRpcNotification<T>`, `JsonRpcRequest<T>`, `JsonRpcResponse<T>`,
  `AcpMessage`, `StoredLogEntry`, `TextContent`, `ImageContent`, `AudioContent`,
  `ResourceLink`, `EmbeddedResource`, `ToolCallLocation`, `DiffContent`,
  `PlainContent`, `TerminalContent`, `ToolCall`, `ToolCallUpdate`, `PlanEntry`,
  `Plan`, `ConfigOptionUpdate`, `SessionNotification`, `ClaudeCodeMeta`,
  `UserShellExecuteResult`, `UserShellExecuteParams`, `QueuedMessage`.
- Types: `JsonRpcMessage`, `ContentBlock`, `ToolCallStatus`, `ToolKind`,
  `CodeToolKind` (= `ToolKind | "question"`), `ToolCallContent`, `SessionUpdate`,
  `AgentThoughtChunk`, `AgentMessageChunk`, `ToolCallSessionUpdate`.
- Guards: `isJsonRpcNotification`, `isJsonRpcRequest`, `isJsonRpcResponse`.

### `<root>/strip-ansi.ts`

`export function stripAnsi(s: string): string` — dependency-free ANSI stripper.
Use in console / execute output rendering.

### `<root>/StepList.tsx`

Ports `<ref>/../../components/ui/StepList.tsx`. PostHog-native (@posthog/icons +
Tailwind). Exports:
- `type StepStatus = 'pending' | 'in_progress' | 'completed' | 'failed'`
- `interface Step { key: string; label: string; status: StepStatus; detail?: string }`
- `function StepIcon({ status, size? }): JSX.Element`
- `function StepList({ steps, size?, gap? }): JSX.Element`
  (`steps: Step[]`, `size?: '1' | '2'`, `gap?: '1' | '2' | '3'`).
Icons: `IconCheckCircle`, `IconCircleDashed` (pending), `IconSpinner`
(spinning), `IconX`.

### `<root>/GitActionMessage.tsx`

Ports `<ref>/GitActionMessage.tsx`. Exports:
- `type GitActionType = 'commit-push' | 'publish' | 'push' | 'pull' | 'sync' | 'create-pr'`
- `function parseGitActionMessage(content: string): { isGitAction: boolean; actionType: GitActionType | null; prompt: string }`
  (signature IDENTICAL to reference).
- `function GitActionMessage({ actionType }: { actionType: GitActionType }): JSX.Element`.
Native: `LemonTag` + `@posthog/icons` (`IconCloud`, `IconGitBranch`,
`IconPullRequest`, `IconRefresh`).

### `<root>/lib/contextColors.ts`

Ports `<ref>/../utils/contextColors.ts`. Radix accent tokens mapped to PostHog
CSS vars. Exports:
- `type ContextCategoryKey`, `interface CategoryStyle { key; label; color }`
- `const CONTEXT_CATEGORIES: readonly CategoryStyle[]`
- `function getOverallUsageColor(percentage: number): string`
- `function formatTokensCompact(tokens: number): string`

### `<root>/lib/acpExtensions.ts`

Vendored from `<code>/packages/agent/src/acp-extensions.ts`. Exports:
- `const POSTHOG_NOTIFICATIONS` (TURN_COMPLETE, ERROR, CONSOLE, STATUS, PROGRESS,
  TASK_NOTIFICATION, COMPACT_BOUNDARY, USAGE_UPDATE, RESOURCES_USED).
- `function isNotification(method: string | undefined, expected): boolean`.

### `<root>/lib/path.ts`

Vendored from `<code>/.../utils/path.ts`. Exports: `getFileName`,
`getFileExtension`, `compactHomePath`.

### `<root>/lib/promptContent.ts`

Vendored from `<code>/.../utils/promptContent.ts`. Exports:
`ATTACHMENT_URI_PREFIX`, `interface AttachmentRef`, `parseAttachmentUri`,
`interface PromptDisplayContent`, `extractPromptDisplayContent(blocks, options?)`.

### `<root>/lib/skillButtons.ts`

Vendored from `<code>/.../skill-buttons/prompts.ts` (id detection only). Exports:
`type SkillButtonId`, `function extractSkillButtonId(blocks): SkillButtonId | null`.

### `<root>/buildConversationItems.ts`  ← 1:1 PORT of `<ref>/buildConversationItems.ts`

**This file also OWNS the `RenderItem`, `UserMessageAttachment`, and
`UserShellExecute` types** (in the reference these lived in the view modules;
moved here to keep the data layer free of React deps — the renderers import
them back from here).

Exports (logic equivalent to reference):
- Types/interfaces: `RenderItem`, `UserMessageAttachment`, `UserShellExecute`,
  `TurnContext`, `ConversationItem`, `LastTurnInfo`, `BuildResult`, `ItemBuilder`,
  `BuildConversationOptions`.
- Functions: `createItemBuilder()`, `markThoughtCompletion(items)`,
  `buildConversationItems(events, isPromptPending, options?)`,
  `processEvent(b, event, options?)`, `finalizeBuilder(b, isPromptPending)`,
  `readLastTurnInfo(b)`.

`RenderItem` variants (the SessionUpdateView switch must cover all): the raw ACP
`SessionUpdate` union PLUS synthetic: `console`, `compact_boundary`, `status`,
`error`, `task_notification`, `progress_group`.

### `<root>/incrementalConversationItems.ts`  ← 1:1 PORT

Exports `createIncrementalConversationBuilder(): { update(events, isPromptPending, options?): BuildResult; reset(): void }`.

### `<root>/mergeConversationItems.ts`  ← 1:1 PORT

Exports `mergeConversationItems({ conversationItems, optimisticItems, queuedItems, isCloud }): ConversationItem[]`.

### `<root>/useConversationItems.ts`  ← PORT of `<ref>/../hooks/useConversationItems.ts`

Exports `useConversationItems(events, isPromptPending, options?): BuildResult`.

### `<root>/parseSessionLogs.ts`

Bridges raw S3 log text / SSE events into `AcpMessage[]`. **Preserves the
index-keyed-object `rawOutput` normalization quirk** from
`<root>/../lib/parse-logs.ts`. Exports:
- `function parseSessionLogs(logs: string): AcpMessage[]`
- `function parseSessionLogEvent(event: Record<string, unknown>, ts?: number): AcpMessage | null`

---

## PRIMITIVES — `<root>/primitives/`

### `primitives/icons.ts`

Reference: phosphor icon names used across all renderers (see map below).
A `Record<string, IconType>` mapping the phosphor names the renderers reference
to `@posthog/icons` components, so porting agents write `ICON_MAP.PencilSimple`
instead of importing phosphor. Export:
- `export const ICONS: Record<string, (props) => JSX.Element>` keyed by the
  phosphor name; plus convenience named re-exports if useful.

Required mapping (phosphor → @posthog/icons):
`ArrowsClockwise→IconRefresh`, `Brain→IconBrain`, `CaretDown→IconChevronDown`,
`CaretRight→IconChevronRight`, `CaretUp→IconChevronDown` (rotate),
`ChatCircle→IconChat`, `Check→IconCheck`, `CheckCircle→IconCheckCircle`,
`Circle→IconCircleDashed`, `CircleNotch→IconSpinner`, `Clock→IconClock`,
`Command→IconBolt`, `Copy→IconCopy`, `File→IconDocument`, `FileText→IconDocument`,
`Folder→IconFolder`, `Globe→IconGlobe`, `Lightning→IconBolt`,
`MagnifyingGlass→IconSearch`, `Minus→IconMinus`, `PencilSimple→IconPencil`,
`Plus→IconPlus`, `Robot→IconAI` (no IconRobot in this version), `SlackLogo→IconChat` (no slack
icon — use chat/document), `Spinner→IconSpinner`, `Stop→IconWarning` (no
IconStop/IconErrorOutline in this version), `Terminal→IconTerminal`,
`Trash→IconTrash`, `Warning→IconWarning`, `Wrench→IconWrench`, `XCircle→IconX`,
`ArrowsOutSimple→IconExpand`, `ArrowsInSimple→IconCollapse`,
`ArrowsLeftRight→IconArrowRightDown`, `ArrowDown→IconArrowRightDown`,
`Question→IconQuestion`, `Circle→IconCircleDashed` (no plain IconCircle).
`Icon` type → use `@posthog/icons` `IconComponent<IconProps>` (exported from
`@posthog/icons`; `IconProps = Omit<ComponentProps<'svg'>, 'children'>`).
NOTE: `@posthog/icons` icons do NOT take a `size` prop — size via
`style={{ fontSize }}` or a `text-*` / `w-*`/`h-*` class.

### `primitives/toolCallUtils.tsx`

Reference: `<ref-su>/toolCallUtils.tsx`. PostHog-native. Exports (keep names &
shapes):
- `interface ToolViewProps { toolCall: ToolCall; turnCancelled?: boolean; turnComplete?: boolean; expanded?: boolean }`
  (`ToolCall` from `<root>/acp-types`).
- `function useToolCallStatus(status: ToolCall['status'], turnCancelled?: boolean, turnComplete?: boolean): { isIncomplete; isLoading; isFailed; wasCancelled; isComplete }`
- `function ToolTitle({ children, className? }): JSX.Element`
- `function StatusIndicators({ isFailed?, wasCancelled? }): JSX.Element` — renders
  "(Failed)" / "(Cancelled)".
- `function LoadingIcon({ icon, isLoading, className? }): JSX.Element`
- `function ExpandableIcon({ icon, isLoading, isExpandable, isExpanded }): JSX.Element`
  — uses `Minus`/`Plus` on hover; map via icons.ts. Spinner via `Spinner` from
  `@posthog/lemon-ui` or `IconSpinner` spinning.
- `function ContentPre({ children }): JSX.Element`
- `function ExpandedContentBox({ children }): JSX.Element`
- `function getContentText(content: ToolCall['content']): string | undefined`
- `interface ImageContentData` + `function getContentImage(content): ImageContentData | null`
- `function getReadToolContent(...)`, `function getLineCount(content): number | null`
- `function compactInput(rawInput: unknown): string | undefined`
- `function formatInput(rawInput: unknown): string | undefined`
- `function stripCodeFences(text: string): string`
- `function truncateText(text, max): string`
- `function getFilename(path: string): string` (delegate to `lib/path.getFileName`)
- `type DiffContent = Extract<ToolCallContent, { type: 'diff' }>`
- `function findDiffContent(content): DiffContent | undefined`
- `interface ResourceLinkData` + `function findResourceLink(...)`.
Native: `Spinner` (@posthog/lemon-ui) replaces `DotsCircleSpinner`; Radix
`Box`/`Text` → `<div>`/`<span>` + Tailwind. Map `text-gray-*` → `text-muted` /
`text-default`, `border-gray-6` → `border-border`.

### `primitives/CodePreview.tsx`

Reference: `<ref-su>/CodePreview.tsx` (+ it used `@pierre/diffs` for diffs and
codemirror highlighting — DO NOT port those). Implement with `CodeSnippet` +
`Language`/`getLanguage`, a **custom unified-diff renderer** (split `oldContent`
vs `content` into +/- lines, color with `bg-success-highlight` /
`bg-danger-highlight`), and an image preview (`<img>` for data/URI content).
Exports:
- `interface CodePreviewProps { content: string; filePath?: string; showPath?: boolean; oldContent?: string | null; firstLineNumber?: number; maxHeight?: string; cacheKey?: string }`
- `function CodePreview(props: CodePreviewProps): JSX.Element`.

### `primitives/MarkdownMessage.tsx`

Reference: the markdown rendering inside `<ref-su>/AgentMessage.tsx`
(`MarkdownRenderer`). Wrap `LemonMarkdown`. Export:
- `function MarkdownMessage({ content, className? }: { content: string; className?: string }): JSX.Element`.
Streaming-friendly: just re-render the full string.

### `primitives/parseFileMentions.tsx`

Reference: `<ref-su>/parseFileMentions.tsx`. Exports (keep names):
- `const InlineMarkdown` (memo component `{ content: string }`)
- `function hasMentionTags(content: string): boolean`
- `const hasFileMentions = hasMentionTags`
- `function parseMentionTags(content: string): ReactNode[]`
- `const parseFileMentions = parseMentionTags`
- `const MentionChip` (memo) — but PREFER importing the chip from
  `FileMentionChip.tsx` below; keep `MentionChip` as a re-export alias.

### `primitives/FileMentionChip.tsx`

Reference: `<ref-su>/FileMentionChip.tsx`. Read-only: render a static chip
(no editor-open click). Export:
- `const FileMentionChip` (memo) `{ path: string; label?: string }` → `JSX.Element`.
Native: `LemonTag` or a plain `<span>` with `IconDocument`.

---

## MESSAGE RENDERERS — `<root>/messages/`

All reference files live in `<ref-su>/`.

| File | Reference | Export & signature | Native components |
|---|---|---|---|
| `AgentMessage.tsx` | `AgentMessage.tsx` | `const AgentMessage` (memo) `{ content: string }` → `JSX.Element` | `MarkdownMessage` / `LemonMarkdown` |
| `UserMessage.tsx` | `UserMessage.tsx` | `const UserMessage` (memo) `{ content: string; timestamp?: number; sourceUrl?: string; attachments?: UserMessageAttachment[]; animate?: boolean }`; ALSO re-export `type UserMessageAttachment` from `<root>/buildConversationItems` | `LemonMarkdown`, `LemonButton` (copy, disabled-safe), `IconDocument`; collapse long content with local state. NO framer-motion. |
| `ThoughtView.tsx` | `ThoughtView.tsx` | `const ThoughtView` (memo) `{ content: string; isLoading: boolean }` → `JSX.Element` | `LemonMarkdown`, `IconBrain`, `IconSpinner` |
| `ConsoleMessage.tsx` | `ConsoleMessage.tsx` | `function ConsoleMessage({ level, message, timestamp? }): JSX.Element` (`level: 'info'\|'debug'\|'warn'\|'error'`) | Tailwind level colors; `stripAnsi` on message |
| `CompactBoundaryView.tsx` | `CompactBoundaryView.tsx` | `function CompactBoundaryView({ trigger, preTokens, contextSize? }): JSX.Element` (`trigger: 'manual'\|'auto'`) | `formatTokensCompact`, `IconRefresh` |
| `StatusNotificationView.tsx` | `StatusNotificationView.tsx` | `function StatusNotificationView({ status, isComplete? }): JSX.Element` | `Spinner`, `IconCheckCircle` |
| `ErrorNotificationView.tsx` | `ErrorNotificationView.tsx` | `function ErrorNotificationView({ errorType, message }): JSX.Element` | `IconWarning`, `bg-danger-highlight` |
| `TaskNotificationView.tsx` | `TaskNotificationView.tsx` | `function TaskNotificationView({ status, summary }): JSX.Element` (`status: 'completed'\|'failed'\|'stopped'`) | `LemonTag`, `IconCheckCircle`/`IconX` |
| `ProgressGroupView.tsx` | `ProgressGroupView.tsx` | `function ProgressGroupView({ steps, isActive, turnComplete? }): JSX.Element` (`steps: Step[]`) | `StepList`, `LemonCollapse` (auto-collapse when `turnComplete`) |
| `QueuedMessageView.tsx` | `QueuedMessageView.tsx` | `function QueuedMessageView({ message, onRemove? }): JSX.Element` (`message: QueuedMessage`) | read-only: ignore/disable `onRemove`; `LemonTag`, `IconClock` |
| `UserShellExecuteView.tsx` | `UserShellExecuteView.tsx` | `function UserShellExecuteView({ item }: { item: UserShellExecute }): JSX.Element`; ALSO re-export `type UserShellExecute` from `<root>/buildConversationItems` | delegates to `ExecuteToolView` |

---

## TOOL RENDERERS — `<root>/tools/`

All reference files in `<ref-su>/`. Unless noted, each takes `ToolViewProps`
from `<root>/primitives/toolCallUtils` and returns `JSX.Element | null`.

| File | Reference | Export & signature | Notes |
|---|---|---|---|
| `ReadToolView.tsx` | `ReadToolView.tsx` | `function ReadToolView(props: ToolViewProps): JSX.Element` | `IconDocument`; `CodePreview` for content |
| `EditToolView.tsx` | `EditToolView.tsx` | `function EditToolView(props: ToolViewProps): JSX.Element` | `IconPencil`; `CodePreview` diff (`oldContent`) |
| `DeleteToolView.tsx` | `DeleteToolView.tsx` | `function DeleteToolView(props: ToolViewProps): JSX.Element` | `IconTrash` |
| `MoveToolView.tsx` | `MoveToolView.tsx` | `function MoveToolView(props: ToolViewProps): JSX.Element` | `IconArrowRightDown` |
| `SearchToolView.tsx` | `SearchToolView.tsx` | `function SearchToolView(props: ToolViewProps): JSX.Element` | `IconSearch` |
| `ExecuteToolView.tsx` | `ExecuteToolView.tsx` | `function ExecuteToolView(props: ToolViewProps): JSX.Element` | `IconTerminal`; `stripAnsi`; `CodeSnippet`(Bash) |
| `ThinkToolView.tsx` | `ThinkToolView.tsx` | `function ThinkToolView(props: ToolViewProps): JSX.Element` | `IconBrain` |
| `FetchToolView.tsx` | `FetchToolView.tsx` | `function FetchToolView(props: ToolViewProps): JSX.Element` | `IconGlobe` |
| `PlanApprovalView.tsx` | `PlanApprovalView.tsx` | `function PlanApprovalView(props: ToolViewProps): JSX.Element` | read-only: render plan + a DISABLED approve/reject; `IconList` |
| `QuestionToolView.tsx` | `QuestionToolView.tsx` | `function QuestionToolView(props: ToolViewProps): JSX.Element` | read-only: show question + disabled options; `IconQuestion` |
| `SubagentToolView.tsx` | `SubagentToolView.tsx` | `function SubagentToolView(props: ToolViewProps & { childItems: ConversationItem[]; turnContext: TurnContext }): JSX.Element` | recurses via `SessionUpdateView`; `IconAI`; `LemonCollapse` |
| `McpToolBlock.tsx` | `McpToolBlock.tsx` | `function McpToolBlock(props: ToolViewProps & { mcpToolName: string }): JSX.Element` | NO iframe host — render result statically; `IconBolt` |
| `ToolCallView.tsx` | `ToolCallView.tsx` | `function ToolCallView(props: ToolViewProps & { agentToolName?: string }): JSX.Element` | generic fallback; `IconWrench` |
| `ToolRow.tsx` | `ToolRow.tsx` | `function ToolRow({ icon, isLoading, isFailed?, wasCancelled?, children }): JSX.Element` (`icon` is an `@posthog/icons` component) | shared row chrome; uses `ExpandableIcon`/`LoadingIcon` |

`ConversationItem` and `TurnContext` import from `<root>/buildConversationItems`.

---

## MISC — `<root>/`

| File | Reference | Export & signature | Notes |
|---|---|---|---|
| `GeneratingIndicator.tsx` | `<ref>/GeneratingIndicator.tsx` | `function GeneratingIndicator(props?): JSX.Element` | `Spinner` + "Generating…"; check ref for props |
| `SessionFooter.tsx` | `<ref>/SessionFooter.tsx` | `function SessionFooter(props): JSX.Element` | read-only summary (duration, stop reason from `LastTurnInfo`); strip live-only props |
| `DiffStatsChip.tsx` | `<ref>/DiffStatsChip.tsx` | `function DiffStatsChip({ task }): JSX.Element` — replace `task: Task` with a plain `{ additions: number; deletions: number }` prop (no `@shared/types`) | `LemonTag`; `+N`/`-N` |
| `GitActionResult.tsx` | `<ref>/GitActionResult.tsx` | `function GitActionResult(props): JSX.Element` — drop live git/tRPC; render static result for a `GitActionType` | check ref for shape; render disabled |

---

## COMPOSITION — `<root>/`

### `SessionUpdateView.tsx`  ← `<ref-su>/SessionUpdateView.tsx`

`export const SessionUpdateView` (memo). Re-export `type RenderItem` FROM
`<root>/buildConversationItems` (do NOT redefine it here).

Props:
```ts
interface SessionUpdateViewProps {
  item: RenderItem
  toolCalls?: Map<string, ToolCall>
  childItems?: Map<string, ConversationItem[]>
  turnCancelled?: boolean
  turnComplete?: boolean
  thoughtComplete?: boolean
}
```
Switch on `item.sessionUpdate` — cover EVERY case:
- `user_message_chunk` → `null`
- `agent_message_chunk` → `AgentMessage` (text only, else null)
- `agent_thought_chunk` → `ThoughtView` (`isLoading={!thoughtComplete}`)
- `tool_call` → `ToolCallBlock` (passes `toolCalls?.get(item.toolCallId) ?? item`,
  `childItems?.get(...)`, `childItemsMap={childItems}`)
- `tool_call_update` → `null`
- `plan` → `null`
- `available_commands_update` → `null`
- `config_option_update` → `null`
- `console` → `ConsoleMessage`
- `compact_boundary` → `CompactBoundaryView`
- `status` → `StatusNotificationView`
- `error` → `ErrorNotificationView`
- `task_notification` → `TaskNotificationView`
- `progress_group` → `ProgressGroupView`
- `default` → `null`

### `ToolCallBlock.tsx`  ← `<ref-su>/ToolCallBlock.tsx`

`export function ToolCallBlock(props: ToolViewProps & { childItems?: ConversationItem[]; childItemsMap?: Map<string, ConversationItem[]> }): JSX.Element | null`.

Dispatch order (cover EVERY branch):
1. Read `toolName` from `toolCall._meta.claudeCode.toolName`.
2. `toolName === 'EnterPlanMode'` → `null`.
3. `(toolName === 'Task' || 'Agent')` AND `childItems.length > 0` →
   `SubagentToolView` (builds child `TurnContext` via `buildChildToolCallsMap`),
   wrapped in `<div className="pl-3">`.
4. `toolName.startsWith('mcp__')` → `McpToolBlock` (`mcpToolName={toolName}`),
   `pl-3`.
5. Else switch on `toolCall.kind`:
   `switch_mode`→`PlanApprovalView`, `execute`→`ExecuteToolView`,
   `read`→`ReadToolView`, `edit`→`EditToolView`, `delete`→`DeleteToolView`,
   `move`→`MoveToolView`, `search`→`SearchToolView`, `think`→`ThinkToolView`,
   `fetch`→`FetchToolView`, `question`→`QuestionToolView`,
   `default`→`ToolCallView` (`agentToolName={toolName}`). Wrap in `pl-3`.
Include private helper `buildChildToolCallsMap(childItems): Map<string, ToolCall>`.

### `ConversationView.tsx`  ← `<ref>/ConversationView.tsx`

`export const ConversationView` (memo). Renders `ConversationItem[]` as a plain
scrollable, read-only list with scroll-to-bottom.

Props (read-only adaptation — STRIP all live/store/git/tRPC/MCP props):
```ts
interface ConversationViewProps {
  events: AcpMessage[]
  isPromptPending?: boolean | null   // default null (cloud/replay)
  promptStartedAt?: number | null
  queuedMessages?: QueuedMessage[]
  showDebugLogs?: boolean
  className?: string
}
```
Behavior:
- `const { items, lastTurnInfo, isCompacting } = useConversationItems(events, isPromptPending ?? null, { showDebugLogs })`.
- Render each `ConversationItem` by `type`: `user_message`→`UserMessage`,
  `git_action`→`GitActionMessage`, `git_action_result`→`GitActionResult`,
  `skill_button_action`→a static label (no live skill button), `session_update`→
  `SessionUpdateView` (pass `turnContext` fields + `thoughtComplete`),
  `turn_cancelled`→static "Cancelled" notice, `user_shell_execute`→
  `UserShellExecuteView`, `queued`→`QueuedMessageView` (read-only).
- Optionally `mergeConversationItems` if queued messages are supplied
  (`isCloud` = whatever caller passes; default `false`).
- Scroll-to-bottom: a `useRef` to the list end + an effect on `items.length`;
  a "scroll to bottom" `LemonButton` (icon `IconArrowRightDown`) when not pinned.
- NO `VirtualizedList`, NO `@pierre` worker pool, NO `useContextUsage` /
  `useConversationSearch` unless trivially reimplemented; prefer omitting.
- Footer: `SessionFooter` driven by `lastTurnInfo` / `isCompacting`.

---

## Token mapping cheat-sheet (Radix → PostHog/Tailwind)

- `text-gray-12` → `text-default`; `text-gray-11`/`text-gray-10` → `text-muted`;
  `text-gray-8` → `text-muted`.
- `text-blue-9` → `text-accent`; `text-green-9` → `text-success`;
  `text-red-9` → `text-danger`; `text-amber-9`/`orange-9` → `text-warning`.
- `bg-accent-3` → `bg-accent-highlight`; `bg-accent-9` → `bg-accent`;
  `border-accent-6` → `border-accent`; `border-gray-6` → `border-border`.
- Radix `<Box>` → `<div>`; `<Flex align="center" gap="2">` →
  `<div className="flex items-center gap-2">`; `<Text>` → `<span>`;
  `<Badge>` → `LemonTag`; `<IconButton>` → `LemonButton size="small" icon={…}`.
- `size={N}` on phosphor icons → `style={{ fontSize: N }}` on `@posthog/icons`.
