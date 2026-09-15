import { Button } from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasShareBodyView } from "./CanvasShareDialog";
import { ShareDialog } from "./ShareDialog";

const off = {
  enabled: false,
  accessToken: null,
  passwordRequired: false,
  allowForking: false,
};

const on = {
  enabled: true,
  accessToken: "9f3c1b2a7d6e4f5a",
  passwordRequired: false,
  allowForking: true,
};

const meta: Meta<typeof CanvasShareBodyView> = {
  title: "Sharing/CanvasShareDialog",
  component: CanvasShareBodyView,
  args: {
    appUrl: "https://us.posthog.com/desktop/canvas/space-42/canvas-7",
    forkUrl: "https://us.posthog.com/desktop/canvas/space-42/canvas-7?fork=1",
    publicUrl: null,
    visibility: "project",
    isPubliclyShareable: true,
    sharing: off,
    isLoading: false,
    isError: false,
    isPending: false,
    newerVersionPublished: false,
    onToggle: () => {},
    onAllowForkingChange: () => {},
  },
  // The dialog frame the container renders around the body, with the footer
  // action it adds once a newer version is published.
  decorators: [
    (Story, context) => (
      <ShareDialog
        title="Share canvas"
        description="Revenue board"
        onClose={() => {}}
        action={
          context.args.newerVersionPublished ? (
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
type Story = StoryObj<typeof CanvasShareBodyView>;

/** Sharing is off: the app link, the copy link, and who they work for. */
export const PublicOff: Story = {};

/** Sharing is on and current: the public link appears, with the toggle that lets viewers copy. */
export const PublicOn: Story = {
  args: {
    publicUrl: "https://us.posthog.com/shared/9f3c1b2a7d6e4f5a",
    sharing: on,
  },
};

/** A publish landed after the link was shared: a note in the body and a Publish changes button. */
export const NewerVersionPublished: Story = {
  args: {
    publicUrl: "https://us.posthog.com/shared/9f3c1b2a7d6e4f5a",
    sharing: on,
    newerVersionPublished: true,
  },
};

/** Nothing has been published yet, so there is nothing to capture. */
export const Unpublished: Story = {
  args: { disabledReason: "Publish the canvas before sharing it publicly." },
};

/** A canvas in a personal space: only the owner can open or share it. */
export const PersonalSpace: Story = {
  args: { visibility: "personal" },
};
