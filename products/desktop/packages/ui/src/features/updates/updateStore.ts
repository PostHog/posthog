import {
  getUpdateUiStatus,
  type UpdateUiStatus,
  updateStore,
} from "@posthog/core/updates/updateStore";
import { useService } from "@posthog/di/react";
import {
  UPDATES_CLIENT,
  type UpdatesClient,
} from "@posthog/ui/features/updates/updatesClient";
import { logger } from "@posthog/ui/shell/logger";
import { useStore } from "zustand";

const log = logger.scope("update-store");

interface UpdateView {
  status: UpdateUiStatus;
  version: string | null;
  availableVersion: string | null;
  releaseNotes: string | null;
  downloadPercent: number | null;
  bytesPerSecond: number | null;
  downloadSizeBytes: number | null;
  isEnabled: boolean;
}

export function useUpdateView(): UpdateView {
  return useStore(updateStore, (state) => ({
    status: state.status,
    version: state.version,
    availableVersion: state.availableVersion,
    releaseNotes: state.releaseNotes,
    downloadPercent: state.downloadPercent,
    bytesPerSecond: state.bytesPerSecond,
    downloadSizeBytes: state.downloadSizeBytes,
    isEnabled: state.isEnabled,
  }));
}

export function useHasActiveUpdate(): boolean {
  return useStore(
    updateStore,
    (state) =>
      state.status === "available" ||
      state.status === "downloading" ||
      state.status === "ready" ||
      state.status === "installing",
  );
}

export function useInstallUpdate(): () => Promise<void> {
  const client = useService<UpdatesClient>(UPDATES_CLIENT);

  return async () => {
    if (getUpdateUiStatus() === "installing") {
      return;
    }

    updateStore.getState().setStatus("installing");

    try {
      const result = await client.install();
      if (!result.installed) {
        log.error("Update install returned not installed");
        updateStore.getState().setStatus("ready");
      }
    } catch (error) {
      log.error("Failed to install update", { error });
      updateStore.getState().setStatus("ready");
    }
  };
}
