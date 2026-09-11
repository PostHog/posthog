import type { Meta, StoryObj } from "@storybook/react";
import { ErrorBoundary } from "./ErrorBoundary";

const meta = {
  title: "Primitives/ErrorBoundary",
  component: ErrorBoundary,
  parameters: {
    layout: "fullscreen",
  },
  decorators: [
    (Story) => (
      <div className="h-screen w-full">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ErrorBoundary>;

export default meta;
type Story = StoryObj<typeof meta>;

function BrokenView(): never {
  throw new Error("Failed to load this view.");
}

export const Default: Story = {
  render: () => (
    <ErrorBoundary>
      <BrokenView />
    </ErrorBoundary>
  ),
};
