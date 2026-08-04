import { CheckCircle, XCircle } from "@phosphor-icons/react";
import {
  deriveUpdateStatus,
  resolveCheckResultAction,
} from "@posthog/core/settings/updateStatus";
import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { Badge, Button, Flex, Spinner, Switch, Text } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useRef, useState } from "react";

const log = logger.scope("updates-settings");

export function UpdatesSettings() {
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

  return (
    <Flex direction="column">
      <SettingRow label="Current version">
        <Flex align="center" gap="2">
          <Button
            variant="ghost"
            size="1"
            onClick={() => useWhatsNewStore.getState().open()}
          >
            View changelog
          </Button>
          <Badge size="1" variant="soft" color="gray">
            {appVersion || "Loading..."}
          </Badge>
        </Flex>
      </SettingRow>

      {updatesEnabled?.enabled ? (
        <>
          <SettingRow
            label="Download updates automatically"
            description="Download new versions in the background and install them on the next quit. When off, you choose when to download each update."
          >
            <Switch
              checked={downloadUpdatesAutomatically}
              onCheckedChange={handleAutoDownloadChange}
              size="1"
            />
          </SettingRow>
          <SettingRow
            label="Dismissible update banners"
            description="Reveal a dismiss button when hovering update banners. A dismissed banner stays hidden until a new update arrives or the app restarts."
          >
            <Switch
              checked={dismissibleUpdateBanners}
              onCheckedChange={handleDismissibleBannersChange}
              size="1"
            />
          </SettingRow>
        </>
      ) : null}

      <SettingRow
        label="Check for updates"
        description="Automatically checks for new versions on startup"
        noBorder
      >
        <Flex align="center" gap="3">
          {updateStatus.message && (
            <Flex align="center" gap="1">
              {updateStatus.type === "info" && checkingForUpdates && (
                <Spinner size="1" />
              )}
              {updateStatus.type === "success" && (
                <CheckCircle size={14} weight="fill" className="text-green-9" />
              )}
              {updateStatus.type === "error" && (
                <XCircle size={14} weight="fill" className="text-red-9" />
              )}
              <Text
                color={
                  updateStatus.type === "error"
                    ? "red"
                    : updateStatus.type === "success"
                      ? "green"
                      : "gray"
                }
                className="text-[13px]"
              >
                {updateStatus.message}
              </Text>
            </Flex>
          )}
          {!updatesDisabled && (
            <Button
              variant="soft"
              size="1"
              onClick={handleCheckForUpdates}
              disabled={checkingForUpdates}
            >
              {checkingForUpdates ? "Checking..." : "Check now"}
            </Button>
          )}
        </Flex>
      </SettingRow>
    </Flex>
  );
}
