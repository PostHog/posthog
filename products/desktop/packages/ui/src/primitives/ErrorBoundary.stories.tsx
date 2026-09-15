import { ErrorBoundary } from "@posthog/ui/primitives/ErrorBoundary";
import type { Meta, StoryObj } from "@storybook/react-vite";

function BrokenView(): never {
  throw new Error("The command center could not render this item.");
}

const meta = {
  title: "Primitives/ErrorBoundary",
  component: ErrorBoundary,
  parameters: { layout: "fullscreen" },
  args: { children: null },
  render: () => (
    <div className="h-screen">
      <ErrorBoundary>
        <BrokenView />
      </ErrorBoundary>
    </div>
  ),
} satisfies Meta<typeof ErrorBoundary>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
