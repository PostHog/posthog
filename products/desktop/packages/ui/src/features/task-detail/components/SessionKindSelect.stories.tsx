import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { type SessionKind, SessionKindSelect } from "./SessionKindSelect";

/**
 * The chip holds no state of its own — the composer does — so the story
 * supplies it, and a pick sticks the way it does above the prompt box.
 */
function Harness({ initialKind }: { initialKind: SessionKind }) {
  const [kind, setKind] = useState<SessionKind>(initialKind);
  return (
    <div className="flex items-center gap-1 p-2">
      <SessionKindSelect value={kind} onChange={setKind} />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Spaces/SessionKindSelect",
  component: Harness,
  args: { initialKind: "code" },
};

export default meta;
type Story = StoryObj<typeof Harness>;

export const Code: Story = {};

/** A canvas session: the composer drops its workspace and repository chips. */
export const Canvas: Story = { args: { initialKind: "canvas" } };

/** A question session: answered in plan mode, so nothing gets changed. */
export const Question: Story = { args: { initialKind: "question" } };
