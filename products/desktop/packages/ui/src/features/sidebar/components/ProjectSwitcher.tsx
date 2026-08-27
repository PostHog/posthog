import {
  Archive,
  ArrowSquareOut,
  Buildings,
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
  Button,
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
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@posthog/quill";
import { EXTERNAL_LINKS } from "@posthog/shared";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  useLogoutMutation,
  useSelectProjectMutation,
  useSwitchOrgMutation,
} from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useProjects } from "@posthog/ui/features/projects/useProjects";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useHoldSidebarPeek } from "@posthog/ui/features/sidebar/useHoldSidebarPeek";
import { useWhatsNewStore } from "@posthog/ui/features/updates/whatsNewStore";
import {
  type MenuFlyoutItem,
  MenuSubFlyout,
  SearchableMenuFlyout,
} from "@posthog/ui/primitives/SearchableMenuFlyout";
import { navigateToArchived } from "@posthog/ui/router/navigationBridge";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { isMac } from "@posthog/ui/utils/platform";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { Avatar, Box } from "@radix-ui/themes";
import { useMemo, useState } from "react";

interface ProjectSwitcherProps {
  appearance?: "row" | "icon";
}

/** The account / project / org menu. */
export function ProjectSwitcher({
  appearance = "row",
}: ProjectSwitcherProps = {}) {
  const [popoverOpen, setPopoverOpen] = useState(false);

  const holdPeek = useHoldSidebarPeek();
  const handleOpenChange = (next: boolean): void => {
    setPopoverOpen(next);
    holdPeek(next);
  };

  const currentOrgId = useAuthStateValue((state) => state.currentOrgId);
  const sessionType = useAuthStateValue((state) => state.sessionType);
  const sessionExpiresAt = useAuthStateValue((state) => state.sessionExpiresAt);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const selectProjectMutation = useSelectProjectMutation();
  const switchOrgMutation = useSwitchOrgMutation();
  const logoutMutation = useLogoutMutation();
  const { groupedProjects, currentProject, currentProjectId } = useProjects();
  // The channels layout has no room for a standing Archived row, so archived
  // tasks live here — a peer of Settings, not buried inside it. Still hidden
  // when there is nothing archived, exactly as the row was.
  const channelsLayout = useChannelsLayout();
  const archivedTaskIds = useArchivedTaskIds();
  const showArchived = channelsLayout && archivedTaskIds.size > 0;

  const isIcon = appearance === "icon";
  const projectName = currentProject?.name ?? "No project selected";
  const projectInitials = projectName.slice(0, 2);

  const currentOrgGroup =
    groupedProjects.find((group) => group.orgId === currentOrgId) ?? null;
  const currentOrgName =
    currentOrgGroup?.orgName ??
    currentProject?.organization.name ??
    "No organization";
  const impersonationExpiry =
    sessionType === "impersonated" && sessionExpiresAt
      ? new Date(sessionExpiresAt).toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
        })
      : null;
  const projectItems = useMemo<MenuFlyoutItem[]>(
    () =>
      (currentOrgGroup?.projects ?? []).map((project) => ({
        id: String(project.id),
        label: project.name,
        current: project.id === currentProjectId,
      })),
    [currentOrgGroup, currentProjectId],
  );

  // Logos aren't in orgProjectsMap, so cross-reference the user's org list.
  const orgItems = useMemo<MenuFlyoutItem[]>(
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

  const handleArchived = () => {
    setPopoverOpen(false);
    navigateToArchived();
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
          isIcon ? (
            <Button
              variant="outline"
              size="icon"
              aria-label={projectName}
              className="shrink-0 font-semibold text-[11px] text-muted-foreground uppercase hover:bg-fill-selected aria-expanded:bg-fill-active"
            >
              {projectInitials}
            </Button>
          ) : (
            <Item
              size="xs"
              className="border-transparent bg-fill-hover py-1.5 hover:bg-fill-selected aria-expanded:bg-fill-active"
            >
              <ItemContent className="select-none gap-0">
                <ItemTitle>{projectName}</ItemTitle>
                <ItemDescription className="text-[11px]">
                  {impersonationExpiry &&
                    `Impersonating until ${impersonationExpiry}`}
                </ItemDescription>
              </ItemContent>
            </Item>
          )
        }
      />

      <DropdownMenuContent
        align={isIcon ? "end" : "start"}
        side={isIcon ? "right" : "bottom"}
        // The rail trigger is one icon wide, so anchor-width would squeeze the
        // menu to nothing.
        className={
          isIcon
            ? "w-64 pt-0"
            : "w-(--anchor-width) max-w-(--anchor-width) pt-0"
        }
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
                  {impersonationExpiry && (
                    <ItemDescription className="text-[11px] text-warning">
                      Impersonated session ends at {impersonationExpiry}
                    </ItemDescription>
                  )}
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
                <MenuSubFlyout className="w-64 p-0">
                  <SearchableMenuFlyout
                    items={projectItems}
                    placeholder="Search projects…"
                    emptyLabel="No projects"
                    onSelect={(id) => handleProjectSelect(Number(id))}
                  />
                </MenuSubFlyout>
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
                <MenuSubFlyout className="w-64 p-0">
                  <SearchableMenuFlyout
                    items={orgItems}
                    placeholder="Search organizations…"
                    emptyLabel="No organizations"
                    onSelect={(id) => handleOrgSelect(id)}
                  />
                </MenuSubFlyout>
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

            {showArchived && (
              <DropdownMenuItem onClick={handleArchived}>
                <Archive size={14} className="text-gray-11" />
                Archived
              </DropdownMenuItem>
            )}

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
