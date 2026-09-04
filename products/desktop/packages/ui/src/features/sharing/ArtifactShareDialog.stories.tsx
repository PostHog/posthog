import type { Meta, StoryObj } from "@storybook/react-vite";
import { ArtifactShareBodyView } from "./ArtifactShareDialog";
import { ShareDialog } from "./ShareDialog";

const meta: Meta<typeof ArtifactShareBodyView> = {
  title: "Sharing/ArtifactShareDialog",
  component: ArtifactShareBodyView,
  args: {
    appUrl:
      "https://us.posthog.com/desktop/task/task-19?scope=task_artifact&item=upload-3",
    publicUrl: null,
    visibility: "project",
    sharing: { enabled: false, accessToken: null, passwordRequired: false },
    isLoading: false,
    isError: false,
    isPending: false,
    onToggle: () => {},
  },
  decorators: [
    (Story) => (
      <ShareDialog
        title="Share file"
        description="report.md"
        onClose={() => {}}
      >
        <Story />
      </ShareDialog>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ArtifactShareBodyView>;

/** Sharing is off: the app link and who it works for. */
export const PublicOff: Story = {};

/** Sharing is on: this upload has a public link. */
export const PublicOn: Story = {
  args: {
    publicUrl: "https://us.posthog.com/shared/4b8e2d1c9a7f3e60",
    sharing: {
      enabled: true,
      accessToken: "4b8e2d1c9a7f3e60",
      passwordRequired: false,
    },
  },
};
