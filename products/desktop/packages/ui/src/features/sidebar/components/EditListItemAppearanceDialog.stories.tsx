import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { EditListItemAppearanceDialog } from "./EditListItemAppearanceDialog";

const meta = {
  title: "Sidebar/Edit list item appearance dialog",
  component: EditListItemAppearanceDialog,
  parameters: {
    layout: "centered",
  },
  decorators: [
    (Story) => {
      useSidebarStore.setState({
        listItemMetadataFields: ["repository", "branch"],
      });
      return <Story />;
    },
  ],
  args: {
    surface: "sidebar",
    open: true,
    onOpenChange: fn(),
  },
} satisfies Meta<typeof EditListItemAppearanceDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
