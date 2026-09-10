import {
  type UpdateUiStatus,
  updateStore,
} from "@posthog/core/updates/updateStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { UpdateBanner } from "@posthog/ui/features/sidebar/components/UpdateBanner";
import type { Meta, StoryObj } from "@storybook/react-vite";

function seedStore(status: UpdateUiStatus): void {
  useSettingsStore.setState({ dismissibleUpdateBanners: false });
  updateStore.setState({
    status,
    isEnabled: true,
    version: status === "available" ? null : "0.24.1",
    availableVersion: "0.24.1",
    downloadPercent: 42,
    downloadSizeBytes: 180 * 1024 * 1024,
  });
}

const meta = {
  title: "Sidebar/UpdateBanner",
  component: UpdateBanner,
} satisfies Meta<typeof UpdateBanner>;

export default meta;

type Story = StoryObj<typeof meta>;

/** The sidebar footer, where the banner lives while that column is on screen. */
export const InSidebar: Story = {
  render: (args) => {
    seedStore("ready");
    return (
      <div className="flex h-[320px] w-[280px] flex-col justify-end bg-chrome">
        <UpdateBanner {...args} />
      </div>
    );
  },
};

/** The title bar, which holds the banner when the sidebar cannot. */
export const InTitleBar: Story = {
  args: { variant: "compact" },
  render: (args) => {
    seedStore("ready");
    return (
      <div className="flex h-[38px] w-[720px] items-center bg-chrome px-3">
        <span className="text-[13px] text-muted-foreground">Tabs</span>
        <div className="ml-auto flex items-center pr-2">
          <UpdateBanner {...args} />
        </div>
      </div>
    );
  },
};

export const Downloading: Story = {
  render: (args) => {
    seedStore("downloading");
    return (
      <div className="flex w-[280px] flex-col bg-chrome">
        <UpdateBanner {...args} />
      </div>
    );
  },
};
