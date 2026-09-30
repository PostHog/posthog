import { ErrorBoundaryFallback } from "@posthog/ui/primitives/ErrorBoundaryFallback";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";

function renderError(message: string, frames: number): Error {
  const error = new TypeError(message);
  const stack = Array.from(
    { length: frames },
    (_, index) =>
      `    at renderItem (app://posthog/assets/index-4f2a9c.js:1${index}:2${index})`,
  );
  error.stack = [`TypeError: ${message}`, ...stack].join("\n");
  return error;
}

const COMPONENT_STACK = [
  "    at SessionView",
  "    at TaskLogsPanel",
  "    at ErrorBoundary",
  "    at App",
].join("\n");

const meta = {
  title: "Primitives/ErrorBoundary",
  component: ErrorBoundaryFallback,
  parameters: { layout: "fullscreen" },
  args: {
    error: renderError("Cannot read properties of undefined (reading 'id')", 6),
    componentStack: COMPONENT_STACK,
    boundaryName: "SessionView",
    onRefresh: fn(),
  },
  render: (args) => (
    <div className="flex h-screen">
      <ErrorBoundaryFallback {...args} />
    </div>
  ),
} satisfies Meta<typeof ErrorBoundaryFallback>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const LongMessage: Story = {
  args: {
    error: renderError(
      "Failed to fetch dynamically imported module: app://posthog/assets/TaskDetailView-9b1c0e7d3f2a4b5c.js because the network request returned an unexpected status code",
      24,
    ),
  },
};

export const WithoutStack: Story = {
  args: {
    error: Object.assign(new Error("Unexpected token < in JSON"), {
      stack: undefined,
    }),
    componentStack: null,
    boundaryName: undefined,
  },
};

/** The fallback inside a narrow pane, as when a side panel crashes next to the sidebar. */
export const NarrowPane: Story = {
  render: (args) => (
    <div className="flex h-screen items-stretch justify-center p-6">
      <div className="flex h-full w-[360px] rounded-md border border-border">
        <ErrorBoundaryFallback {...args} />
      </div>
    </div>
  ),
};
