import { FileTextIcon, PlusIcon } from "@phosphor-icons/react";
import type { SpaceFileSummary } from "@posthog/api-client/posthog-client";
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
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { NewSpaceFileDialog } from "@posthog/ui/features/space-files/NewSpaceFileDialog";
import {
  useSpaceFileMutations,
  useSpaceFiles,
} from "@posthog/ui/features/space-files/useSpaceFiles";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { type ReactElement, useMemo, useState } from "react";

interface FileSection {
  channelId: string;
  label: string;
  files: SpaceFileSummary[];
}

function buildSections(
  files: SpaceFileSummary[],
  channelNames: Map<string, string>,
  query: string,
): FileSection[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const grouped = new Map<string, SpaceFileSummary[]>();
  for (const file of files) {
    const channelName = channelNames.get(file.channel_id) ?? "Unknown space";
    if (
      !file.name.toLocaleLowerCase().includes(normalizedQuery) &&
      !channelName.toLocaleLowerCase().includes(normalizedQuery)
    ) {
      continue;
    }
    const current = grouped.get(file.channel_id) ?? [];
    current.push(file);
    grouped.set(file.channel_id, current);
  }
  return [...grouped.entries()]
    .map(([channelId, groupedFiles]) => ({
      channelId,
      label: channelNames.get(channelId) ?? "Unknown space",
      files: groupedFiles.sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

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
  const channelNames = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel.name])),
    [channels],
  );
  const sections = useMemo(
    () => buildSections(files, channelNames, query),
    [channelNames, files, query],
  );
  const fileIds = sections.flatMap((section) =>
    section.files.map((file) => file.id),
  );

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
            <Button
              size="sm"
              variant="outline"
              data-attr="new-space-file"
              onClick={() => setNewFileOpen(true)}
            >
              <PlusIcon size={14} />
              New file…
            </Button>
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
                  {query ? "No files match" : "No files yet"}
                </EmptyTitle>
                <EmptyDescription>
                  {query
                    ? "Try another search."
                    : "Create a Markdown file in a space."}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col gap-px">
              {sections.map((section) => (
                <div key={section.channelId}>
                  <MenuLabel>{section.label}</MenuLabel>
                  {section.files.map((file) => (
                    <AutocompleteItem
                      key={file.id}
                      value={file.id}
                      nativeButton
                      className="h-auto w-full py-1.5 text-left ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0"
                      onClick={() => open(file)}
                    >
                      <FileTextIcon size={14} />
                      <span className="truncate text-[13px]">{file.name}</span>
                    </AutocompleteItem>
                  ))}
                </div>
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
