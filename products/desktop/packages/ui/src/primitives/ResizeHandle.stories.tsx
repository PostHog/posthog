import { Kbd } from "@posthog/quill";
import { ResizeHandle } from "@posthog/ui/primitives/ResizeHandle";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";

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
      const [width, setWidth] = useState(340);
      const [isResizing, setIsResizing] = useState(false);
      const boxRef = useRef<HTMLDivElement>(null);
      const rightRef = useRef(0);
      return (
        // A transform, like every real caller has: it makes this the containing
        // block for a fixed shield, which is why the shield is portaled out.
        <div className="flex h-screen" style={{ transform: "translateX(0)" }}>
          <div className="flex-1 bg-fill-hover p-3 text-[13px]">
            Drag the grip. The cursor holds across this pane too.
          </div>
          <div
            ref={boxRef}
            className="relative border-border border-l bg-background p-3 text-[13px]"
            style={{ width }}
          >
            {width}px
            <ResizeHandle
              {...args}
              isResizing={isResizing}
              setIsResizing={setIsResizing}
              onDragStart={() => {
                rightRef.current =
                  boxRef.current?.getBoundingClientRect().right ?? 0;
              }}
              onDrag={(event) =>
                setWidth(Math.max(120, rightRef.current - event.clientX))
              }
            />
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
