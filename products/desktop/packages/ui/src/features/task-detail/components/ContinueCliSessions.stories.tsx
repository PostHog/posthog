import type { DiscoveredTask } from "@posthog/core/setup/types";
import { Flex, Text } from "@radix-ui/themes";
import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  type CliSession,
  ContinueCliSessionsInline,
  SessionPickerDialog,
} from "./ContinueCliSessions";
import { SuggestedTaskCard } from "./SuggestedTaskCard";

const session = (overrides: Partial<CliSession> = {}): CliSession => ({
  sourceSessionId: "sess-1",
  title: "Review the auth refactor",
  lastPrompt: "look at the token-refresh edge cases",
  updatedAt: "2026-06-25T09:00:00Z",
  gitBranch: "feat/auth",
  status: "new",
  ...overrides,
});

const manySessions = (count: number): CliSession[] =>
  Array.from({ length: count }, (_, i) =>
    session({
      sourceSessionId: `sess-${i + 1}`,
      title: `Session ${i + 1}`,
      updatedAt: `2026-06-${String(25 - i).padStart(2, "0")}T09:00:00Z`,
    }),
  );

const meta: Meta<typeof ContinueCliSessionsInline> = {
  title: "Task Detail/ContinueCliSessions",
  component: ContinueCliSessionsInline,
  args: {
    runningId: null,
    onContinue: () => {},
  },
  // Match the new-task composer's column width so the card sizes realistically.
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 560, margin: "2rem auto", padding: "0 1rem" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ContinueCliSessionsInline>;

/** One past session → just the card, no "See all". Provenance: "Claude Code ·". */
export const OneSession: Story = {
  args: { sessions: [session()] },
};

/** More than one → the latest card plus a "See all N" into the archive dialog. */
export const WithArchive: Story = {
  args: { sessions: manySessions(8) },
};

/**
 * A very long title must truncate so the "· import from Claude Code" label is
 * never pushed off or clipped — the label stays pinned, the title takes an
 * ellipsis.
 */
export const LongTitle: Story = {
  args: {
    sessions: [
      session({
        title:
          "Refactor the session reconnection saga to dedupe in-flight resume requests and surface a typed branch-mismatch prompt before checkout",
      }),
    ],
  },
};

/** No git branch → meta collapses to "Claude Code · 2h". */
export const NoBranch: Story = {
  args: { sessions: [session({ gitBranch: null })] },
};

/** Neither a title nor a last prompt → falls back to a generic label. */
export const Untitled: Story = {
  args: { sessions: [session({ title: null, lastPrompt: null })] },
};

/** No title but a last prompt → the prompt becomes the title. */
export const TitleFromPrompt: Story = {
  args: {
    sessions: [
      session({ title: null, lastPrompt: "refactor the session store" }),
    ],
  },
};

/** An import is in flight → the card shows a spinner and is disabled. */
export const Importing: Story = {
  args: {
    sessions: manySessions(4),
    runningId: "sess-1",
  },
};

/** The "See all" archive: a searchable list that scales past a handful. */
export const Picker: Story = {
  render: () => (
    <SessionPickerDialog
      sessions={manySessions(12)}
      open
      onOpenChange={() => {}}
      runningId={null}
      onContinue={() => {}}
    />
  ),
};

const discoveredTask = (
  overrides: Partial<DiscoveredTask>,
): DiscoveredTask => ({
  id: "dt-1",
  title: "Race in the event-stream sender",
  description:
    "The retry deadline can fire after the stream closes, leaking a timer.",
  category: "bug",
  // Discovery (agent source) is off, so the panel only ever shows enricher tasks.
  source: "enricher",
  ...overrides,
});

/** The enricher's discovered-task cards — the rest of the suggestions list. */
function DiscoveredTaskCards() {
  const tasks = [
    discoveredTask({}),
    discoveredTask({
      id: "dt-2",
      title: "Drop the dead jsonl-hydration branch",
      description:
        "encodeCwdToProjectKey has an unreachable fallback after the refactor.",
      category: "dead_code",
    }),
  ];
  return (
    <>
      {tasks.map((task) => (
        <SuggestedTaskCard
          key={task.id}
          task={task}
          onSelect={() => {}}
          onDismiss={() => {}}
        />
      ))}
    </>
  );
}

/**
 * The whole suggestions list as it renders in the panel: one "Suggestions"
 * header, the Claude Code resume card as the first item (with "See all"), then
 * the enricher's discovered tasks. No separate heading or section for CLI.
 */
export const WithOtherSuggestions: Story = {
  render: () => (
    <div className="mt-3 flex flex-col gap-2">
      <Flex align="center" justify="between" className="px-2.5">
        <Text size="1" weight="medium" className="text-(--gray-11)">
          Suggestions
        </Text>
      </Flex>
      <ContinueCliSessionsInline
        sessions={manySessions(5)}
        runningId={null}
        onContinue={() => {}}
      />
      <DiscoveredTaskCards />
    </div>
  ),
};
