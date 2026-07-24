import { Menu as BaseMenu } from "@base-ui/react/menu";
import {
  ArrowSquareOut,
  Buildings,
  Check,
  DiscordLogo,
  FolderSimple,
  Gear,
  Gift,
  Info,
  Keyboard,
  Plus,
  ShieldCheck,
  SignOut,
} from "@phosphor-icons/react";
import {
  Autocomplete,
  AutocompleteCollection,
  AutocompleteGroup,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteList,
  AutocompleteStatus,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@posthog/quill";
import { EXTERNAL_LINKS } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  useLogoutMutation,
  useSelectProjectMutation,
  useSwitchOrgMutation,
} from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useProjects } from "@posthog/ui/features/projects/useProjects";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useHoldSidebarPeek } from "@posthog/ui/features/sidebar/useHoldSidebarPeek";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { isMac } from "@posthog/ui/utils/platform";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { Avatar, Box } from "@radix-ui/themes";
import { ChevronRightIcon } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

// The two-line user/project card used at the bottom of the sidebar.
export function ProjectSwitcher() {
  const [popoverOpen, setPopoverOpen] = useState(false);

  const holdPeek = useHoldSidebarPeek();
  const handleOpenChange = (next: boolean): void => {
    setPopoverOpen(next);
    holdPeek(next);
  };

  const currentOrgId = useAuthStateValue((state) => state.currentOrgId);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const selectProjectMutation = useSelectProjectMutation();
  const switchOrgMutation = useSwitchOrgMutation();
  const logoutMutation = useLogoutMutation();
  const { groupedProjects, currentProject, currentProjectId } = useProjects();

  const currentOrgGroup =
    groupedProjects.find((group) => group.orgId === currentOrgId) ?? null;
  const currentOrgName =
    currentOrgGroup?.orgName ??
    currentProject?.organization.name ??
    "No organization";
  const projectItems = useMemo<FlyoutItem[]>(
    () =>
      (currentOrgGroup?.projects ?? []).map((project) => ({
        id: String(project.id),
        label: project.name,
        current: project.id === currentProjectId,
      })),
    [currentOrgGroup, currentProjectId],
  );

  // Logos aren't in orgProjectsMap, so cross-reference the user's org list.
  const orgItems = useMemo<FlyoutItem[]>(
    () =>
      groupedProjects.map((group) => {
        const logoMediaId = currentUser?.organizations?.find(
          (org) => org.id === group.orgId,
        )?.logo_media_id;
        const logoSrc = logoMediaId
          ? (getPostHogUrl(`/uploaded_media/${logoMediaId}`) ?? undefined)
          : undefined;
        return {
          id: group.orgId,
          label: group.orgName,
          current: group.orgId === currentOrgId,
          icon: (
            <OrgAvatar
              orgId={group.orgId}
              name={group.orgName}
              logoSrc={logoSrc}
            />
          ),
        };
      }),
    [groupedProjects, currentOrgId, currentUser],
  );

  const handleProjectSelect = (projectId: number) => {
    if (projectId !== currentProjectId) {
      selectProjectMutation.mutate(projectId);
    }
    setPopoverOpen(false);
  };

  const handleOrgSelect = (orgId: string) => {
    if (orgId !== currentOrgId) {
      switchOrgMutation.mutate(orgId);
    }
    setPopoverOpen(false);
  };

  const handleCreateProject = () => {
    const url = getPostHogUrl("/organization/create-project");
    if (url) openExternalUrl(url);
    setPopoverOpen(false);
  };

  const handleCreateOrg = () => {
    const url = getPostHogUrl("/create-organization");
    if (url) openExternalUrl(url);
    setPopoverOpen(false);
  };

  const handleSettings = () => {
    setPopoverOpen(false);
    openSettings();
  };

  const handleKeyboardShortcuts = () => {
    setPopoverOpen(false);
    openSettings("shortcuts");
  };

  const handleOpenExternal = (url: string) => {
    openExternalUrl(url);
    setPopoverOpen(false);
  };

  const handleDiscord = () => {
    openExternalUrl(EXTERNAL_LINKS.discord);
    setPopoverOpen(false);
  };

  const handleViewChangelog = () => {
    useWhatsNewStore.getState().open();
    setPopoverOpen(false);
  };

  const handleLogout = () => {
    setPopoverOpen(false);
    logoutMutation.mutate();
  };

  return (
    <DropdownMenu open={popoverOpen} onOpenChange={handleOpenChange}>
      <DropdownMenuTrigger
        render={
          <Item
            size="xs"
            className="border-border hover:bg-fill-hover aria-expanded:bg-fill-active"
          >
            <ItemContent className="select-none gap-0">
              <ItemTitle>
                {currentProject?.name ?? "No project selected"}
              </ItemTitle>
              <ItemDescription className="text-[11px]">
                {currentUser?.email ?? "No email"}
              </ItemDescription>
            </ItemContent>
            <ItemActions>
              <ChevronRightIcon className="size-4 rotate-270 group-aria-expanded/item:rotate-90" />
            </ItemActions>
          </Item>
        }
      />

      <DropdownMenuContent
        align="start"
        side="bottom"
        className="w-(--anchor-width) max-w-(--anchor-width) pt-0"
        sideOffset={4}
      >
        <Box>
          <Box className="-mx-1 mb-1 border-border border-b">
            {currentUser ? (
              <Item className="p-2">
                <ItemContent className="gap-0">
                  <ItemTitle>
                    {currentUser.first_name && (
                      <span>
                        {currentUser.first_name}
                        {currentUser.last_name && ` ${currentUser.last_name}`}
                      </span>
                    )}
                  </ItemTitle>
                  <ItemDescription className="text-[11px]">
                    {currentUser.email}
                  </ItemDescription>
                </ItemContent>
              </Item>
            ) : (
              <>
                <Box className="mt-1 h-3.5 w-20 animate-pulse rounded bg-gray-6" />
                <Box className="mt-1 h-3 w-32 animate-pulse rounded bg-gray-5" />
              </>
            )}
          </Box>

          <Box className="flex flex-col gap-px">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Project</DropdownMenuLabel>

              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <FolderSimple size={14} className="text-gray-11" />
                  {currentProject?.name ?? "No project selected"}
                </DropdownMenuSubTrigger>
                <PinnedSubContent className="w-64 p-0">
                  <SearchableFlyout
                    items={projectItems}
                    placeholder="Search projects…"
                    emptyLabel="No projects"
                    onSelect={(id) => handleProjectSelect(Number(id))}
                  />
                </PinnedSubContent>
              </DropdownMenuSub>

              <DropdownMenuItem onClick={handleCreateProject}>
                <Plus size={14} className="text-gray-11" />
                Create project
                <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
              </DropdownMenuItem>
            </DropdownMenuGroup>

            <DropdownMenuGroup>
              <DropdownMenuLabel>Organization</DropdownMenuLabel>

              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <Buildings size={14} className="text-gray-11" />
                  {currentOrgName}
                </DropdownMenuSubTrigger>
                <PinnedSubContent className="w-64 p-0">
                  <SearchableFlyout
                    items={orgItems}
                    placeholder="Search organizations…"
                    emptyLabel="No organizations"
                    onSelect={(id) => handleOrgSelect(id)}
                  />
                </PinnedSubContent>
              </DropdownMenuSub>

              <DropdownMenuItem onClick={handleCreateOrg}>
                <Plus size={14} className="text-gray-11" />
                Create organization
                <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
              </DropdownMenuItem>
            </DropdownMenuGroup>

            <DropdownMenuSeparator />

            <DropdownMenuItem onClick={handleDiscord}>
              <DiscordLogo size={14} className="text-gray-11" />
              Join our Discord
              <ArrowSquareOut size={14} className="ml-auto text-gray-11" />
            </DropdownMenuItem>

            <DropdownMenuItem onClick={handleViewChangelog}>
              <Gift size={14} className="text-gray-11" />
              View changelog
            </DropdownMenuItem>

            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Info size={14} className="text-gray-11" />
                Learn more
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent side="right" sideOffset={4}>
                <DropdownMenuItem
                  onClick={() => handleOpenExternal(EXTERNAL_LINKS.website)}
                >
                  <ArrowSquareOut size={14} className="text-gray-11" />
                  Website
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => handleOpenExternal(EXTERNAL_LINKS.privacy)}
                >
                  <ShieldCheck size={14} className="text-gray-11" />
                  Privacy Policy
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleKeyboardShortcuts}>
                  <Keyboard size={14} className="text-gray-11" />
                  Keyboard Shortcuts
                  <DropdownMenuShortcut>
                    {isMac ? "⌘/" : "Ctrl+/"}
                  </DropdownMenuShortcut>
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>

            <DropdownMenuItem onClick={handleSettings}>
              <Gear size={14} className="text-gray-11" />
              Settings
              <DropdownMenuShortcut>
                {isMac ? "⌘," : "Ctrl+,"}
              </DropdownMenuShortcut>
            </DropdownMenuItem>

            <DropdownMenuSeparator />

            <DropdownMenuItem onClick={handleLogout}>
              <SignOut size={14} className="text-gray-11" />
              Log out
            </DropdownMenuItem>
          </Box>
        </Box>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type FlyoutItem = {
  id: string;
  label: string;
  current: boolean;
  icon?: ReactNode;
};
type FlyoutSection = { items: FlyoutItem[] };

// Deterministic palette so an org keeps the same fallback color across renders.
const ORG_AVATAR_COLORS = [
  "tomato",
  "ruby",
  "crimson",
  "pink",
  "plum",
  "purple",
  "violet",
  "iris",
  "indigo",
  "blue",
  "cyan",
  "teal",
  "jade",
  "green",
  "grass",
  "orange",
  "amber",
] as const;

function orgAvatarColor(orgId: string): (typeof ORG_AVATAR_COLORS)[number] {
  let hash = 0;
  for (const char of orgId) {
    hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  }
  return ORG_AVATAR_COLORS[hash % ORG_AVATAR_COLORS.length];
}

function orgInitials(name: string): string {
  // Drop leading emoji/symbols so the initial is a real letter, like web.
  const letters = name.replace(/[^\p{L}\p{N}]/gu, "");
  return (letters.charAt(0) || "?").toUpperCase();
}

interface OrgAvatarProps {
  orgId: string;
  name: string;
  logoSrc?: string;
}

function OrgAvatar({ orgId, name, logoSrc }: OrgAvatarProps) {
  return (
    <Avatar
      src={logoSrc}
      fallback={orgInitials(name)}
      color={orgAvatarColor(orgId)}
      radius="medium"
      size="1"
      style={{ width: 20, height: 20 }}
    />
  );
}

// Quill's DropdownMenuSubContent doesn't forward collisionAvoidance to the
// base-ui positioner, so a flyout near the viewport bottom flips upward and
// hangs from its bottom edge. This variant pins align="start" (open downward)
// by disabling alignment flipping, mirroring quill's markup/classes otherwise.
// TODO(quill): the quill-menu__* classes and data attributes below are quill's
// compiled internals, not public API — a quill upgrade that renames them would
// silently strip this flyout's styling. Drop this component in favor of
// DropdownMenuSubContent once quill exposes a collisionAvoidance prop.
function PinnedSubContent({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <BaseMenu.Portal>
      <BaseMenu.Positioner
        data-quill
        data-quill-portal="popover"
        className="isolate outline-none"
        align="start"
        alignOffset={-3}
        side="inline-end"
        sideOffset={4}
        collisionAvoidance={{ align: "none" }}
      >
        <BaseMenu.Popup
          data-slot="dropdown-menu-sub-content"
          className={`quill-menu__content quill-menu__sub-content w-auto ${className ?? ""}`}
        >
          <div className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">
            {children}
          </div>
        </BaseMenu.Popup>
      </BaseMenu.Positioner>
    </BaseMenu.Portal>
  );
}

interface SearchableFlyoutProps {
  items: FlyoutItem[];
  placeholder: string;
  emptyLabel: string;
  onSelect: (id: string) => void;
}

function SearchableFlyout({
  items,
  placeholder,
  emptyLabel,
  onSelect,
}: SearchableFlyoutProps) {
  const [query, setQuery] = useState("");
  // Active item first as the anchor when switching; the rest sorted the same
  // way the web app orders them (locale-aware, which floats emoji-prefixed
  // names above plain ones).
  const sections = useMemo<FlyoutSection[]>(
    () => [
      {
        items: [
          ...items.filter((item) => item.current),
          ...items
            .filter((item) => !item.current)
            .sort((a, b) => a.label.localeCompare(b.label)),
        ],
      },
    ],
    [items],
  );

  return (
    // Keep keystrokes away from the surrounding menu: its typeahead handler
    // sits on the submenu popup and would swallow typing meant for the search
    // input. Escape still bubbles so the menu can close.
    // biome-ignore lint/a11y/noStaticElementInteractions: keyboard fencing only
    <div
      onKeyDown={(event) => {
        if (event.key !== "Escape") event.stopPropagation();
      }}
    >
      <Autocomplete<FlyoutItem>
        inline
        defaultOpen
        items={sections}
        value={query}
        autoHighlight="always"
        onValueChange={(val, eventDetails) => {
          if (eventDetails.reason !== "input-change") return;
          if (typeof val === "string") setQuery(val);
        }}
        filter={(item, q) => {
          if (!q) return true;
          return item.label.toLowerCase().includes(q.toLowerCase());
        }}
      >
        <AutocompleteInput placeholder={placeholder} autoFocus showClear />
        {/* Suppress the default "{count} results" line; only show empty states. */}
        <AutocompleteStatus>
          {(count: number) =>
            count === 0 ? (
              query ? (
                <span>
                  No matches for <strong>"{query}"</strong>
                </span>
              ) : (
                <span>{emptyLabel}</span>
              )
            ) : null
          }
        </AutocompleteStatus>
        {/* Long lists get a FIXED height so the popup doesn't resize (and
            jump) while filtering. Kept short enough that the whole flyout
            fits below either trigger row, so the popup itself never grows
            a second scrollbar. */}
        <AutocompleteList
          className={`${items.length > 5 ? "h-40" : "max-h-40"} p-0 pb-0`}
        >
          {(section: FlyoutSection) => (
            <AutocompleteGroup items={section.items} className="p-0">
              <AutocompleteCollection>
                {(item: FlyoutItem) => (
                  <AutocompleteItem
                    key={item.id}
                    value={item.id}
                    onClick={() => onSelect(item.id)}
                    className="flex items-center gap-2 ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0"
                  >
                    <span className="flex w-4 shrink-0 items-center justify-center">
                      {item.current && (
                        <Check size={14} className="text-accent-11" />
                      )}
                    </span>
                    {item.icon && (
                      <span className="flex shrink-0 items-center">
                        {item.icon}
                      </span>
                    )}
                    <span className="truncate text-[13px]">{item.label}</span>
                  </AutocompleteItem>
                )}
              </AutocompleteCollection>
            </AutocompleteGroup>
          )}
        </AutocompleteList>
      </Autocomplete>
    </div>
  );
}
