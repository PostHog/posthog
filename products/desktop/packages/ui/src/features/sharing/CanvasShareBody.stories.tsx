import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasShareBodyView } from "./CanvasShareBody";
import { ShareDialog } from "./ShareModal";

const off = {
  enabled: false,
  accessToken: null,
  passwordRequired: false,
  allowForking: false,
};

const meta: Meta<typeof CanvasShareBodyView> = {
  title: "Sharing/CanvasShareBody",
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
    onToggle: () => {},
    onAllowForkingChange: () => {},
  },
  decorators: [
    (Story) => (
      <ShareDialog
        title="Share canvas"
        description="Revenue board"
        onClose={() => {}}
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

/** Sharing is on: the public link appears, with the toggle that lets viewers copy. */
export const PublicOn: Story = {
  args: {
    publicUrl: "https://us.posthog.com/shared/9f3c1b2a7d6e4f5a",
    sharing: {
      enabled: true,
      accessToken: "9f3c1b2a7d6e4f5a",
      passwordRequired: false,
      allowForking: true,
    },
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
