import {
  ArrowsSplit,
  Cloud,
  Cube,
  Laptop,
  Plus,
  Star,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemMenuItem,
  ItemTitle,
  MenuLabel,
} from "@posthog/quill";
import type { Adapter, WorkspaceMode } from "@posthog/shared";
import { useAdapterSubscription } from "@posthog/ui/features/settings/adapterSubscription";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useCallback, useMemo, useState } from "react";
import {
  type CloudTarget,
  type CloudTargetOption,
  cloudTargetKey,
  DEFAULT_CLOUD_TARGET,
} from "../cloudTargets";
import { useCloudModeEnabled } from "../hooks/useCloudModeEnabled";
import { useCloudTargetOptions } from "../hooks/useCloudTarget";

export type { WorkspaceMode };

const SUBSCRIPTION_IN_USE_LABEL: Record<Adapter, string> = {
  codex: "Using Codex subscription",
  claude: "Using Claude subscription",
};

interface WorkspaceModeSelectProps {
  value: WorkspaceMode;
  onChange: (mode: WorkspaceMode) => void;
  size?: "1" | "2";
  disabled?: boolean;
  overrideModes?: WorkspaceMode[];
  adapter?: Adapter;
  cloudTarget?: CloudTarget;
  onCloudTargetChange?: (target: CloudTarget) => void;
}

const LOCAL_MODES: {
  mode: WorkspaceMode;
  label: string;
  description: string;
  icon: React.ReactNode;
}[] = [
  {
    mode: "worktree",
    label: "Worktree",
    description: "Create a copy of your local project to work in parallel",
    icon: <ArrowsSplit size={14} weight="regular" className="rotate-270" />,
  },
  {
    mode: "local",
    label: "Local",
    description: "Edits your repo directly on current branch",
    icon: <Laptop size={14} weight="regular" />,
  },
];

const CLOUD_ICON = <Cloud size={14} weight="regular" />;

const IMAGE_ICON = <Cube size={14} weight="regular" />;

const ICON_BUTTON_CLASS =
  "flex cursor-pointer items-center justify-center rounded-sm border-0 bg-transparent p-0.5 text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground";

export function WorkspaceModeSelect({
  value,
  onChange,
  disabled,
  overrideModes,
  adapter,
  cloudTarget = DEFAULT_CLOUD_TARGET,
  onCloudTargetChange,
}: WorkspaceModeSelectProps) {
  const { localWorkspaces } = useHostCapabilities();
  const cloudModeEnabled = useCloudModeEnabled();
  const codexSubscription = useAdapterSubscription("codex");
  const claudeSubscription = useAdapterSubscription("claude");
  const adapterSubscription = adapter
    ? { codex: codexSubscription, claude: claudeSubscription }[adapter]
    : undefined;
  const subscriptionInUseLabel =
    adapter &&
    adapterSubscription?.flagEnabled &&
    adapterSubscription.subscriptionOn &&
    adapterSubscription.loggedIn
      ? SUBSCRIPTION_IN_USE_LABEL[adapter]
      : null;

  const { options, favoriteKey, toggleFavorite } = useCloudTargetOptions();
  const [menuOpen, setMenuOpen] = useState(false);

  const environmentOptions = options.filter(
    (option) => option.target.kind !== "image",
  );
  const imageOptions = options.filter(
    (option) => option.target.kind === "image",
  );

  const handleAddEnvironment = useCallback(() => {
    setMenuOpen(false);
    openSettings("cloud-environments", "create");
  }, []);

  const selectTarget = useCallback(
    (target: CloudTarget) => {
      onChange("cloud");
      onCloudTargetChange?.(target);
    },
    [onChange, onCloudTargetChange],
  );

  const showCloud = overrideModes
    ? overrideModes.includes("cloud")
    : cloudModeEnabled;

  const localModes = useMemo(
    () =>
      // Hide worktree/local modes on cloud-only hosts.
      localWorkspaces
        ? LOCAL_MODES.filter(
            (m) => !overrideModes || overrideModes.includes(m.mode),
          )
        : [],
    [overrideModes, localWorkspaces],
  );

  const selectedTargetName = useMemo(() => {
    if (value !== "cloud" || cloudTarget.kind === "default") return null;
    const key = cloudTargetKey(cloudTarget);
    return options.find((option) => option.key === key)?.name ?? null;
  }, [value, cloudTarget, options]);

  const triggerLabel = useMemo(() => {
    if (value === "cloud") {
      return ["Cloud", selectedTargetName].filter(Boolean).join(" · ");
    }
    return LOCAL_MODES.find((m) => m.mode === value)?.label ?? "Worktree";
  }, [value, selectedTargetName]);

  const triggerIcon = useMemo(() => {
    if (value === "cloud") return CLOUD_ICON;
    return (
      LOCAL_MODES.find((m) => m.mode === value)?.icon ?? LOCAL_MODES[0].icon
    );
  }, [value]);

  return (
    <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label="Workspace mode"
          >
            <span className="text-muted-foreground">{triggerIcon}</span>
            {triggerLabel}
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="w-auto min-w-[280px]"
      >
        {localModes.length > 0 && (
          <div className="flex items-center justify-between px-2 py-1">
            <MenuLabel className="p-0">Local</MenuLabel>
            {subscriptionInUseLabel && (
              <span className="text-[11px] text-muted-foreground">
                {subscriptionInUseLabel}
              </span>
            )}
          </div>
        )}

        <DropdownMenuGroup>
          {localModes.map((item) => (
            <DropdownMenuItem
              key={item.mode}
              onClick={() => onChange(item.mode)}
              render={
                <ItemMenuItem size="xs" className="w-full">
                  <ItemMedia variant="icon" className="mt-2 ml-2">
                    <span>{item.icon}</span>
                  </ItemMedia>
                  <ItemContent variant="menuItem">
                    <ItemTitle>{item.label}</ItemTitle>
                    <ItemDescription className="whitespace-nowrap leading-none">
                      {item.description}
                    </ItemDescription>
                  </ItemContent>
                </ItemMenuItem>
              }
            />
          ))}
        </DropdownMenuGroup>

        {showCloud && options.length === 1 && (
          <DropdownMenuItem
            onClick={() => selectTarget(DEFAULT_CLOUD_TARGET)}
            render={
              <ItemMenuItem size="xs" className="w-full">
                <ItemMedia variant="icon" className="mt-2 ml-2">
                  <span>{CLOUD_ICON}</span>
                </ItemMedia>
                <ItemContent variant="menuItem">
                  <ItemTitle>Cloud</ItemTitle>
                  <ItemDescription className="whitespace-nowrap leading-none">
                    Run in a cloud sandbox
                  </ItemDescription>
                </ItemContent>
              </ItemMenuItem>
            }
          />
        )}

        {showCloud && options.length > 1 && (
          <>
            <DropdownMenuSeparator />
            <div className="flex items-center justify-between px-2 py-1">
              <MenuLabel className="p-0">Cloud environments</MenuLabel>
              <button
                type="button"
                onClick={handleAddEnvironment}
                aria-label="Add cloud environment"
                className={ICON_BUTTON_CLASS}
              >
                <Plus size={12} />
              </button>
            </div>

            <DropdownMenuGroup>
              {environmentOptions.map((option) => (
                <CloudTargetItem
                  key={option.key}
                  option={option}
                  isFavorite={favoriteKey === option.key}
                  onSelect={selectTarget}
                  onToggleFavorite={toggleFavorite}
                />
              ))}
            </DropdownMenuGroup>

            {imageOptions.length > 0 && (
              <>
                <div className="px-2 py-1">
                  <MenuLabel className="p-0">Images</MenuLabel>
                </div>
                <DropdownMenuGroup>
                  {imageOptions.map((option) => (
                    <CloudTargetItem
                      key={option.key}
                      option={option}
                      isFavorite={favoriteKey === option.key}
                      onSelect={selectTarget}
                      onToggleFavorite={toggleFavorite}
                    />
                  ))}
                </DropdownMenuGroup>
              </>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function CloudTargetItem({
  option,
  isFavorite,
  onSelect,
  onToggleFavorite,
}: {
  option: CloudTargetOption;
  isFavorite: boolean;
  onSelect: (target: CloudTarget) => void;
  onToggleFavorite: (target: CloudTarget) => void;
}) {
  const icon = option.target.kind === "image" ? IMAGE_ICON : CLOUD_ICON;
  return (
    <DropdownMenuItem
      onClick={() => onSelect(option.target)}
      render={
        <ItemMenuItem size="xs" className="w-full" render={<div />}>
          <ItemMedia variant="icon" className="mt-2 ml-2">
            <span>{icon}</span>
          </ItemMedia>
          <ItemContent variant="menuItem">
            <ItemTitle>{option.name}</ItemTitle>
            <ItemDescription className="whitespace-nowrap leading-none">
              {option.description}
            </ItemDescription>
          </ItemContent>
          <ItemActions className="mr-1.5 ml-auto self-center">
            <button
              type="button"
              tabIndex={-1}
              aria-label={
                isFavorite
                  ? `Stop using ${option.name} by default`
                  : `Use ${option.name} by default`
              }
              aria-pressed={isFavorite}
              onPointerDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onToggleFavorite(option.target);
              }}
              className={cn(
                "flex cursor-pointer items-center justify-center rounded-sm border-0 bg-transparent p-0.5 transition-colors hover:text-foreground",
                isFavorite
                  ? "text-foreground"
                  : "text-muted-foreground opacity-0 group-hover/dropdown-menu-item:opacity-100",
              )}
            >
              <Star size={12} weight={isFavorite ? "fill" : "regular"} />
            </button>
          </ItemActions>
        </ItemMenuItem>
      }
    />
  );
}
