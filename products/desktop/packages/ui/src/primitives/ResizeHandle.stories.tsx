import { Kbd } from "@posthog/quill";
import { ResizeHandle } from "@posthog/ui/primitives/ResizeHandle";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

/**
 * The grab strip a resizable panel is dragged by. Rest the pointer on the
 * hairline for a second to see what it says, and drag it to see the cursor hold
 * across the whole window.
 */
const meta: Meta<typeof ResizeHandle> = {
  title: "Primitives/ResizeHandle",
  component: ResizeHandle,
  parameters: { layout: "fullscreen" },
  args: { edge: "left", tooltip: "Resize", isResizing: false },
  render: (args) => {
    const Demo = () => {
      const [isResizing, setIsResizing] = useState(false);
      return (
        <div className="flex h-screen">
          <div className="flex-1 bg-fill-hover" />
          <div className="relative w-[340px] border-border border-l bg-background p-3 text-[13px]">
            A panel with a grip on its {args.edge} edge.
            <ResizeHandle
              {...args}
              isResizing={isResizing}
              onMouseDown={() => setIsResizing(true)}
            />
            {isResizing && (
              <button
                type="button"
                className="mt-2 underline"
                onClick={() => setIsResizing(false)}
              >
                stop resizing
              </button>
            )}
          </div>
        </div>
      );
    };
    return <Demo />;
  },
};

export default meta;
type Story = StoryObj<typeof ResizeHandle>;

export const Resting: Story = {};

export const WithShortcut: Story = {
  args: {
    tooltip: (
      <>
        Resize
        <span className="flex items-center gap-1 text-background/70">
          <Kbd>⌘B</Kbd>
          to toggle
        </span>
      </>
    ),
  },
};
