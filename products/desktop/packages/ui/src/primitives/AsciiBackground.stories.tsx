import { AsciiBackground } from "@posthog/ui/primitives/AsciiBackground";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Primitives/AsciiBackground",
  component: AsciiBackground,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof AsciiBackground>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => (
    <div className="relative h-[600px] w-full overflow-hidden bg-(--color-background)">
      <AsciiBackground />
    </div>
  ),
};

/** How it reads behind a centered composer — the surface it was built for. */
export const BehindAComposer: Story = {
  render: () => (
    <div className="relative flex h-[600px] w-full items-center justify-center overflow-hidden bg-(--color-background)">
      <AsciiBackground />
      <div className="z-[1] flex w-full max-w-[600px] flex-col gap-2">
        <div className="rounded-md border border-gray-6 bg-gray-2 px-3.5 py-3 text-(--gray-9) text-sm">
          What do you want to ship?
        </div>
        <div className="grid grid-cols-2 gap-2">
          {["Fix a bug", "Build a new feature"].map((label) => (
            <div
              key={label}
              className="rounded-md border border-gray-5 bg-gray-2 px-3 py-2.5 font-medium text-(--gray-12) text-sm"
            >
              {label}
            </div>
          ))}
        </div>
      </div>
    </div>
  ),
};
