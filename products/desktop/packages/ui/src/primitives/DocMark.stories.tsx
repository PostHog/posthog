import type { Meta, StoryObj } from "@storybook/react-vite";
import { DocMark, type DocMarkState, type DocMarkVariant } from "./DocMark";
import "@posthog/ui/features/docs/components/docs.css";

const meta: Meta<typeof DocMark> = {
  title: "Docs/Mark",
  component: DocMark,
};

export default meta;
type Story = StoryObj<typeof DocMark>;

const STATES: Array<[DocMarkVariant, DocMarkState, string]> = [
  ["agent", "still", "agent, done"],
  ["agent", "working", "agent, working"],
  ["agent", "waiting", "agent, waiting on a person"],
  ["agent", "failed", "agent, failed"],
  ["discussion", "open", "people, open"],
  ["discussion", "handled", "people, handled"],
];

/** Every state the margin can show, at the margin's size and the inline size. */
export const AllStates: Story = {
  render: () => (
    <div className="grid grid-cols-[auto_auto_1fr] items-center gap-x-6 gap-y-3 p-6 text-sm">
      {STATES.map(([variant, state, label]) => (
        <div key={label} className="contents">
          <DocMark
            variant={variant}
            state={state}
            size={16}
            count={variant === "discussion" ? 3 : undefined}
          />
          <DocMark variant={variant} state={state} size={11} />
          <span className="text-(--gray-11)">{label}</span>
        </div>
      ))}
    </div>
  ),
};
