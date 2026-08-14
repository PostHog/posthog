import { TipsSection } from "@posthog/ui/features/settings/sections/TipsSettings";
import { retireTeachingTip } from "@posthog/ui/primitives/TeachingTip";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof TipsSection> = {
  title: "Settings/Tips",
  component: TipsSection,
  parameters: { layout: "padded" },
};

export default meta;
type Story = StoryObj<typeof TipsSection>;

/** Nothing dismissed for good yet, so there is nothing to put back. */
export const Default: Story = {};

export const SomethingDismissedForGood: Story = {
  decorators: [
    (Story) => {
      retireTeachingTip("right-panel-artifacts");
      return <Story />;
    },
  ],
};
