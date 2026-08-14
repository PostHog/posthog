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

/** Nothing turned off yet, so there is nothing to put back. */
export const NothingTurnedOff: Story = {};

export const SomethingTurnedOff: Story = {
  decorators: [
    (Story) => {
      retireTeachingTip("right-panel-artifacts");
      return <Story />;
    },
  ],
};
