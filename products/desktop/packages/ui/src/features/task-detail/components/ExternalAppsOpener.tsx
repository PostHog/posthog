import { CodeIcon, CopyIcon } from "@phosphor-icons/react";
import {
  Button,
  ButtonGroup,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { ChevronDown } from "lucide-react";
import { useCallback } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { SHORTCUTS } from "../../command/keyboard-shortcuts";
import { useExternalAppAction } from "../../external-apps/useExternalAppAction";
import { useExternalApps } from "../../external-apps/useExternalApps";

const THUMBNAIL_ICON_SIZE = 20;
const DROPDOWN_ICON_SIZE = 20;

interface ExternalAppsOpenerProps {
  targetPath: string | null;
}

export function ExternalAppsOpener({ targetPath }: ExternalAppsOpenerProps) {
  const openExternalApp = useExternalAppAction();
  const { detectedApps, defaultApp, isLoading, setLastUsedApp } =
    useExternalApps();

  const handleOpenDefault = useCallback(async () => {
    if (!defaultApp || !targetPath) return;
    const displayName = targetPath.split("/").pop() || targetPath;
    await openExternalApp(
      { type: "open-in-app", appId: defaultApp.id },
      targetPath,
      displayName,
    );
  }, [openExternalApp, defaultApp, targetPath]);

  const handleOpenWith = useCallback(
    async (appId: string) => {
      if (!targetPath) return;
      const displayName = targetPath.split("/").pop() || targetPath;
      await openExternalApp(
        { type: "open-in-app", appId },
        targetPath,
        displayName,
      );
      await setLastUsedApp(appId);
    },
    [openExternalApp, targetPath, setLastUsedApp],
  );

  const handleCopyPath = useCallback(async () => {
    if (!targetPath) return;
    const displayName = targetPath.split("/").pop() || targetPath;
    await openExternalApp({ type: "copy-path" }, targetPath, displayName);
  }, [openExternalApp, targetPath]);

  useHotkeys(
    SHORTCUTS.OPEN_IN_EDITOR,
    (event) => {
      event.preventDefault();
      handleOpenDefault();
    },
    { enableOnFormTags: ["INPUT", "TEXTAREA", "SELECT"] },
    [handleOpenDefault],
  );

  useHotkeys(
    SHORTCUTS.COPY_PATH,
    (event) => {
      event.preventDefault();
      handleCopyPath();
    },
    { enableOnFormTags: ["INPUT", "TEXTAREA", "SELECT"] },
    [handleCopyPath],
  );

  if (!targetPath) {
    return null;
  }

  const isReady = !isLoading && detectedApps.length > 0;

  return (
    <ButtonGroup className="no-drag">
      <Button
        size="icon-sm"
        variant="outline"
        aria-label={`Open in ${defaultApp?.name ?? "editor"}`}
        onClick={handleOpenDefault}
        disabled={!isReady || !defaultApp}
      >
        {defaultApp?.icon ? (
          <img
            src={defaultApp.icon}
            width={DROPDOWN_ICON_SIZE}
            height={DROPDOWN_ICON_SIZE}
            alt=""
            className="rounded-[2px]"
          />
        ) : (
          <CodeIcon size={DROPDOWN_ICON_SIZE} weight="regular" />
        )}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="More editor options"
            />
          }
        >
          <ChevronDown size={10} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[150px]">
          {detectedApps.map((app) => (
            <DropdownMenuItem
              key={app.id}
              onClick={() => handleOpenWith(app.id)}
            >
              {app.icon ? (
                <img
                  src={app.icon}
                  width={THUMBNAIL_ICON_SIZE}
                  height={THUMBNAIL_ICON_SIZE}
                  alt=""
                />
              ) : (
                <CodeIcon size={THUMBNAIL_ICON_SIZE} weight="regular" />
              )}
              {app.name}
              {app.id === defaultApp?.id && (
                <DropdownMenuShortcut>⌘O</DropdownMenuShortcut>
              )}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={handleCopyPath}>
            <CopyIcon size={THUMBNAIL_ICON_SIZE} weight="regular" />
            Copy Path
            <DropdownMenuShortcut>⌘⇧C</DropdownMenuShortcut>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </ButtonGroup>
  );
}
