import {
  type UpdateUiStatus,
  updateStore,
} from "@posthog/core/updates/updateStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { UpdateBanner } from "@posthog/ui/features/sidebar/components/UpdateBanner";
import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";

function withUpdateState(status: UpdateUiStatus): Decorator {
  return function WithUpdateState(Story) {
    useEffect(() => {
      const previousUpdate = updateStore.getState();
      const previousDismissible =
        useSettingsStore.getState().dismissibleUpdateBanners;
      useSettingsStore.setState({ dismissibleUpdateBanners: false });
      updateStore.setState({
        status,
        isEnabled: true,
        version: status === "available" ? null : "0.24.1",
        availableVersion: "0.24.1",
        downloadPercent: 42,
        downloadSizeBytes: 180 * 1024 * 1024,
      });
      return () => {
        updateStore.setState(previousUpdate);
        useSettingsStore.setState({
          dismissibleUpdateBanners: previousDismissible,
        });
      };
    }, [status]);
    return <Story />;
  };
}

const meta = {
  title: "Sidebar/UpdateBanner",
  component: UpdateBanner,
} satisfies Meta<typeof UpdateBanner>;

export default meta;

type Story = StoryObj<typeof meta>;

export const InSidebar: Story = {
  decorators: [withUpdateState("ready")],
  render: (args) => (
    <div className="flex h-[320px] w-[280px] flex-col justify-end bg-chrome">
      <UpdateBanner {...args} />
    </div>
  ),
};

export const InTitleBar: Story = {
  args: { variant: "compact" },
  decorators: [withUpdateState("ready")],
  render: (args) => (
    <div className="flex h-[38px] w-[720px] items-center bg-chrome px-3">
      <span className="text-[13px] text-muted-foreground">Tabs</span>
      <div className="ml-auto flex items-center pr-2">
        <UpdateBanner {...args} />
      </div>
    </div>
  ),
};

export const Downloading: Story = {
  decorators: [withUpdateState("downloading")],
  render: (args) => (
    <div className="flex w-[280px] flex-col bg-chrome">
      <UpdateBanner {...args} />
    </div>
  ),
};
