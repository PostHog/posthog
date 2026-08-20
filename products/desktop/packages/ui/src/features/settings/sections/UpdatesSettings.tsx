import { CheckCircle, XCircle } from "@phosphor-icons/react";
import {
  deriveUpdateStatus,
  resolveCheckResultAction,
} from "@posthog/core/settings/updateStatus";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Spinner, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useRef, useState } from "react";

const log = logger.scope("updates-settings");

export function UpdatesSection() {
  const trpc = useHostTRPC();
  const { data: appVersion } = useQuery(trpc.os.getAppVersion.queryOptions());
  const { data: updatesEnabled } = useQuery(
    trpc.updates.isEnabled.queryOptions(),
  );
  const downloadUpdatesAutomatically = useSettingsStore(
    (state) => state.downloadUpdatesAutomatically,
  );
  const setDownloadUpdatesAutomatically = useSettingsStore(
    (state) => state.setDownloadUpdatesAutomatically,
  );
  const dismissibleUpdateBanners = useSettingsStore(
    (state) => state.dismissibleUpdateBanners,
  );
  const setDismissibleUpdateBanners = useSettingsStore(
    (state) => state.setDismissibleUpdateBanners,
  );
  const [checkingForUpdates, setCheckingForUpdates] = useState(false);
  const [updatesDisabled, setUpdatesDisabled] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<{
    message?: string;
    type?: "info" | "success" | "error";
  }>({});
  const hasCheckedRef = useRef(false);

  const checkUpdatesMutation = useMutation(
    trpc.updates.check.mutationOptions(),
  );

  const handleCheckForUpdates = useCallback(async () => {
    setCheckingForUpdates(true);
    setUpdateStatus({ message: "Checking for updates...", type: "info" });

    try {
      const result = await checkUpdatesMutation.mutateAsync();

      const action = resolveCheckResultAction(result);
      if (!action) {
        return;
      }

      if (action.updatesDisabled) {
        setUpdatesDisabled(true);
      }
      setUpdateStatus({ message: action.message, type: action.type });
      setCheckingForUpdates(false);
    } catch (error) {
      log.error("Failed to check for updates:", error);
      setUpdateStatus({
        message: "An unexpected error occurred",
        type: "error",
      });
      setCheckingForUpdates(false);
    }
  }, [checkUpdatesMutation]);

  const handleAutoDownloadChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "download_updates_automatically",
        new_value: checked,
        old_value: !checked,
      });
      setDownloadUpdatesAutomatically(checked);
    },
    [setDownloadUpdatesAutomatically],
  );

  const handleDismissibleBannersChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "dismissible_update_banners",
        new_value: checked,
        old_value: !checked,
      });
      setDismissibleUpdateBanners(checked);
    },
    [setDismissibleUpdateBanners],
  );

  useEffect(() => {
    if (!hasCheckedRef.current) {
      hasCheckedRef.current = true;
      handleCheckForUpdates();
    }
  }, [handleCheckForUpdates]);

  useSubscription(
    trpc.updates.onStatus.subscriptionOptions(undefined, {
      onData: (status) => {
        const derived = deriveUpdateStatus(status);
        if (derived.message) {
          setUpdateStatus({ message: derived.message, type: derived.type });
        }
        if (derived.checking === false) {
          setCheckingForUpdates(false);
        }
      },
    }),
  );

  const statusLine = updateStatus.message && (
    <span className="inline-flex items-center gap-1">
      {updateStatus.type === "info" && checkingForUpdates && (
        <Spinner className="size-3" />
      )}
      {updateStatus.type === "success" && (
        <CheckCircle size={13} weight="fill" className="text-green-9" />
      )}
      {updateStatus.type === "error" && (
        <XCircle size={13} weight="fill" className="text-red-9" />
      )}
      <span
        className={
          updateStatus.type === "error"
            ? "text-red-11"
            : updateStatus.type === "success"
              ? "text-green-11"
              : undefined
        }
      >
        {updateStatus.message}
      </span>
    </span>
  );

  return (
    <SettingsSection label="Updates">
      <SettingsCard>
        <SettingsCardRow
          label={
            <span className="inline-flex items-baseline gap-2">
              Version
              <span className="font-mono font-normal text-[12px] text-gray-11">
                {appVersion ?? "…"}
              </span>
            </span>
          }
          description={statusLine}
        >
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="link-muted"
              size="sm"
              onClick={() => useWhatsNewStore.getState().open()}
            >
              Changelog
            </Button>
            {!updatesDisabled && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleCheckForUpdates}
                disabled={checkingForUpdates}
              >
                {checkingForUpdates ? "Checking..." : "Check now"}
              </Button>
            )}
          </div>
        </SettingsCardRow>

        {updatesEnabled?.enabled && (
          <>
            <SettingsCardRow
              label="Download updates automatically"
              description="New versions download in the background and install on the next quit"
            >
              <Switch
                size="sm"
                checked={downloadUpdatesAutomatically}
                onCheckedChange={handleAutoDownloadChange}
              />
            </SettingsCardRow>
            <SettingsCardRow
              label="Dismissible update banners"
              description="Hovering an update banner reveals a dismiss button"
            >
              <Switch
                size="sm"
                checked={dismissibleUpdateBanners}
                onCheckedChange={handleDismissibleBannersChange}
              />
            </SettingsCardRow>
          </>
        )}
      </SettingsCard>
    </SettingsSection>
  );
}
