import { Button } from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ArtifactShareBodyView } from "./ArtifactShareDialog";
import { ShareDialog } from "./ShareDialog";

const on = {
  enabled: true,
  accessToken: "4b8e2d1c9a7f3e60",
  passwordRequired: false,
  sharedArtifactId: "upload-3",
  latestArtifactId: "upload-3",
};

const meta: Meta<typeof ArtifactShareBodyView> = {
  title: "Sharing/ArtifactShareDialog",
  component: ArtifactShareBodyView,
  args: {
    appUrl:
      "https://us.posthog.com/desktop/task/task-19?scope=task_artifact&item=upload-3",
    publicUrl: null,
    visibility: "project",
    sharing: {
      enabled: false,
      accessToken: null,
      passwordRequired: false,
      sharedArtifactId: null,
      latestArtifactId: "upload-3",
    },
    isLoading: false,
    isError: false,
    isPending: false,
    newerUploadExists: false,
    onToggle: () => {},
  },
  // The dialog frame the container renders around the body, with the footer
  // action it adds once the file was uploaded again.
  decorators: [
    (Story, context) => (
      <ShareDialog
        title="Share file"
        description="report.md"
        onClose={() => {}}
        action={
          context.args.newerUploadExists ? (
            <Button variant="primary" size="sm">
              Publish changes
            </Button>
          ) : null
        }
      >
        <Story />
      </ShareDialog>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ArtifactShareBodyView>;

/** Sharing is off: the team link and who it works for. */
export const PublicOff: Story = {};

/** Sharing is on and current: the file has a public link. */
export const PublicOn: Story = {
  args: {
    publicUrl: "https://us.posthog.com/shared/4b8e2d1c9a7f3e60",
    sharing: on,
  },
};

/** The file was uploaded again after sharing: a note in the body and a Publish changes button. */
export const NewerUploadExists: Story = {
  args: {
    publicUrl: "https://us.posthog.com/shared/4b8e2d1c9a7f3e60",
    sharing: { ...on, latestArtifactId: "upload-4" },
    newerUploadExists: true,
  },
};
