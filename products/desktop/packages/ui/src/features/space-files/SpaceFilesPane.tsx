import { FileTextIcon, PlusIcon } from "@phosphor-icons/react";
import type { SpaceFileSummary } from "@posthog/api-client/posthog-client";
import {
  buildSpaceFileSections,
  hasCustomizedSpaceFileList,
} from "@posthog/core/canvas/spaceFileList";
import {
  Autocomplete,
  AutocompleteItem,
  AutocompleteList,
  Button,
  cn,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  MenuLabel,
} from "@posthog/quill";
import { formatAbsoluteDateTime, formatRelativeAge } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { buildCanvasSpaceOptions } from "@posthog/ui/features/canvas/components/canvasSpaceOptions";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { NewSpaceFileDialog } from "@posthog/ui/features/space-files/NewSpaceFileDialog";
import { SpaceFileFilterMenu } from "@posthog/ui/features/space-files/SpaceFileFilterMenu";
import { useSpaceFileListStore } from "@posthog/ui/features/space-files/spaceFileListStore";
import {
  useSpaceFileMutations,
  useSpaceFiles,
} from "@posthog/ui/features/space-files/useSpaceFiles";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { Fragment, type ReactElement, useMemo, useState } from "react";

export function SpaceFilesPane({
  className,
}: {
  className?: string;
}): ReactElement {
  const { channels } = useChannels();
  const { files, isLoading, isError, error, reload } = useSpaceFiles();
  const { create, isCreating } = useSpaceFileMutations();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [newFileOpen, setNewFileOpen] = useState(false);
  const settings = useSpaceFileListStore((state) => state.settings);
  const setSettings = useSpaceFileListStore((state) => state.setSettings);
  const spaceNames = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel.name])),
    [channels],
  );
  const spaceOptions = useMemo(
    () => buildCanvasSpaceOptions(channels),
    [channels],
  );
  const sections = useMemo(
    () => buildSpaceFileSections({ files, spaceNames, query, settings }),
    [files, spaceNames, query, settings],
  );
  const fileIds = sections.flatMap((section) =>
    section.files.map((file) => file.id),
  );
  const filtered = hasCustomizedSpaceFileList(settings);

  const open = (file: SpaceFileSummary): void => {
    void navigate({ to: "/files", search: { file: file.id } });
  };

  return (
    <Autocomplete<string>
      inline
      open
      value={query}
      items={fileIds}
      filter={null}
      onValueChange={(value, details) => {
        if (details.reason === "input-change" && typeof value === "string") {
          setQuery(value);
        }
      }}
    >
      <div className={cn("flex min-h-0 flex-col", className)}>
        <SidebarSearchHeader
          title="Files"
          query={query}
          placeholder="Search files…"
          searchLabel="Search files"
          onClear={() => setQuery("")}
          actions={
            <>
              <SpaceFileFilterMenu
                spaceOptions={spaceOptions}
                settings={settings}
                onChange={setSettings}
              />
              <Button
                size="sm"
                variant="outline"
                data-attr="new-space-file"
                onClick={() => setNewFileOpen(true)}
              >
                <PlusIcon size={14} />
                New file…
              </Button>
            </>
          }
        />
        <AutocompleteList className="sidebar-autocomplete-tree scroll-mask-8 !max-h-none !p-1.5 min-h-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <LoadingState className="py-10" />
          ) : isError ? (
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileTextIcon />
                </EmptyMedia>
                <EmptyTitle>Couldn't load files</EmptyTitle>
                <EmptyDescription>
                  {error?.message ?? "Try again shortly."}
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void reload()}
                >
                  Try again
                </Button>
              </EmptyContent>
            </Empty>
          ) : sections.length === 0 ? (
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileTextIcon />
                </EmptyMedia>
                <EmptyTitle>
                  {query || filtered ? "No files match" : "No files yet"}
                </EmptyTitle>
                <EmptyDescription>
                  {query || filtered
                    ? "Try another search, or clear the filters."
                    : "Create a Markdown file in a space."}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col gap-px">
              {sections.map((section) => (
                <Fragment key={section.key}>
                  {section.label ? (
                    <MenuLabel>{section.label}</MenuLabel>
                  ) : null}
                  {section.files.map((file) => {
                    const spaceName =
                      spaceNames.get(file.channel_id) ?? "Unknown space";
                    return (
                      <AutocompleteItem
                        key={file.id}
                        value={file.id}
                        nativeButton
                        className="h-auto w-full items-start py-1.5 text-left ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-start [&>span]:gap-2"
                        onClick={() => open(file)}
                      >
                        <FileTextIcon size={14} />
                        <span className="min-w-0">
                          <span className="block truncate text-[13px]">
                            {file.name}
                          </span>
                          <span
                            className="block truncate text-muted-foreground text-xxs"
                            title={formatAbsoluteDateTime(file.updated_at)}
                          >
                            {spaceName} · {formatRelativeAge(file.updated_at)}
                          </span>
                        </span>
                      </AutocompleteItem>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          )}
        </AutocompleteList>
        <NewSpaceFileDialog
          channels={channels}
          open={newFileOpen}
          isCreating={isCreating}
          onOpenChange={setNewFileOpen}
          onCreate={async ({ channelId, name }) => {
            try {
              const file = await create({
                channel_id: channelId,
                name,
                content: "",
              });
              track(ANALYTICS_EVENTS.SPACE_FILE_ACTION, {
                action_type: "create",
                file_id: file.id,
                channel_id: file.channel_id,
                success: true,
              });
              void navigate({ to: "/files", search: { file: file.id } });
            } catch (error) {
              track(ANALYTICS_EVENTS.SPACE_FILE_ACTION, {
                action_type: "create",
                channel_id: channelId,
                success: false,
              });
              throw error;
            }
          }}
        />
      </div>
    </Autocomplete>
  );
}
