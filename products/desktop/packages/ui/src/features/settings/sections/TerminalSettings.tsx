import { X } from "@phosphor-icons/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS, compactHomePath } from "@posthog/shared";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import {
  type TerminalFont,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { useDebounce } from "@posthog/ui/primitives/hooks/useDebounce";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { Flex, Select, Switch, Text, TextField } from "@radix-ui/themes";
import { useEffect, useState } from "react";

const log = logger.scope("terminal-settings");

export function TerminalSettings() {
  const terminalFont = useSettingsStore((s) => s.terminalFont);
  const setTerminalFont = useSettingsStore((s) => s.setTerminalFont);
  const terminalCustomFontFamily = useSettingsStore(
    (s) => s.terminalCustomFontFamily,
  );
  const setTerminalCustomFontFamily = useSettingsStore(
    (s) => s.setTerminalCustomFontFamily,
  );
  const terminalGpuRendering = useSettingsStore((s) => s.terminalGpuRendering);
  const setTerminalGpuRendering = useSettingsStore(
    (s) => s.setTerminalGpuRendering,
  );
  const terminalDefaultCwd = useSettingsStore((s) => s.terminalDefaultCwd);
  const setTerminalDefaultCwd = useSettingsStore(
    (s) => s.setTerminalDefaultCwd,
  );

  const hostClient = useHostTRPCClient();
  const { localWorkspaces } = useHostCapabilities();
  const [isChoosingDirectory, setIsChoosingDirectory] = useState(false);

  const [draftCustomFont, setDraftCustomFont] = useState(
    terminalCustomFontFamily,
  );
  const debouncedCustomFont = useDebounce(draftCustomFont, 500);

  // Pull external changes (hydration, devtools) into the draft.
  useEffect(() => {
    setDraftCustomFont(terminalCustomFontFamily);
  }, [terminalCustomFontFamily]);

  // Commit the debounced draft back to the store. The equality guard breaks
  // the draft<->store loop: writing the store would re-fire the pull-in effect
  // above, which would re-fire this one without it.
  useEffect(() => {
    if (debouncedCustomFont === terminalCustomFontFamily) return;
    setTerminalCustomFontFamily(debouncedCustomFont);
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "terminal_custom_font_family",
      new_value: debouncedCustomFont.length > 0,
    });
  }, [
    debouncedCustomFont,
    terminalCustomFontFamily,
    setTerminalCustomFontFamily,
  ]);

  const handleFontChange = (value: TerminalFont) => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "terminal_font",
      new_value: value,
      old_value: terminalFont,
    });
    setTerminalFont(value);
  };

  const handleGpuRenderingChange = (enabled: boolean) => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "terminal_gpu_rendering",
      new_value: enabled,
      old_value: terminalGpuRendering,
    });
    setTerminalGpuRendering(enabled);
  };

  const handleDefaultCwdChange = (path: string) => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "terminal_default_cwd",
      new_value: path.length > 0,
      old_value: terminalDefaultCwd.length > 0,
    });
    setTerminalDefaultCwd(path);
  };

  const handleChooseDefaultCwd = async () => {
    if (isChoosingDirectory) return;
    setIsChoosingDirectory(true);
    try {
      const path = await hostClient.os.selectDirectory.query();
      if (path) handleDefaultCwdChange(path);
    } catch (error) {
      log.error("Failed to open directory picker", { error });
      toast.error("Failed to open directory picker");
    } finally {
      setIsChoosingDirectory(false);
    }
  };

  const showCustomInput = terminalFont === "custom";

  return (
    <Flex direction="column" gap="1" py="4">
      {localWorkspaces && (
        <SettingRow
          label="Default directory"
          description="Choose which directory new terminal sessions open in. Leave this unset to use the directory you most recently worked in."
        >
          <Flex align="center" gap="2" className="min-w-0">
            {terminalDefaultCwd && (
              <>
                <Text
                  className="max-w-[220px] truncate text-[12px]"
                  title={terminalDefaultCwd}
                >
                  {compactHomePath(terminalDefaultCwd)}
                </Text>
                <button
                  type="button"
                  aria-label="Clear default directory"
                  className="cursor-pointer p-0 opacity-60 hover:opacity-100"
                  onClick={() => handleDefaultCwdChange("")}
                >
                  <X size={12} />
                </button>
              </>
            )}
            <Button
              size="sm"
              variant="outline"
              loading={isChoosingDirectory}
              onClick={() => void handleChooseDefaultCwd()}
            >
              {terminalDefaultCwd ? "Change…" : "Choose directory…"}
            </Button>
          </Flex>
        </SettingRow>
      )}

      <SettingRow
        label="Font"
        description="Font used to render the terminal output"
      >
        <Select.Root
          value={terminalFont}
          onValueChange={(value) => handleFontChange(value as TerminalFont)}
          size="1"
        >
          <Select.Trigger className="min-w-[160px]" />
          <Select.Content>
            <Select.Item value="berkeley-mono">Berkeley Mono</Select.Item>
            <Select.Item value="jetbrains-mono">JetBrains Mono</Select.Item>
            <Select.Item value="system">System monospace</Select.Item>
            <Select.Item value="custom">Custom</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      {showCustomInput && (
        <SettingRow
          label="Custom font family"
          description="Any CSS font-family value. Example: Fira Code, Cascadia Code"
        >
          <Flex direction="column" align="end" gap="1">
            <TextField.Root
              value={draftCustomFont}
              onChange={(e) => setDraftCustomFont(e.target.value)}
              placeholder="Fira Code"
              size="1"
              className="min-w-[240px]"
            />
            <Text color="gray" className="text-[12px]">
              Falls back to Berkeley Mono if unavailable
            </Text>
          </Flex>
        </SettingRow>
      )}

      <SettingRow
        label="GPU rendering"
        description="Render the terminal with WebGL for smoother output under heavy load. Disable if you hit graphical glitches."
        noBorder
      >
        <Switch
          checked={terminalGpuRendering}
          onCheckedChange={handleGpuRenderingChange}
          size="1"
        />
      </SettingRow>
    </Flex>
  );
}
