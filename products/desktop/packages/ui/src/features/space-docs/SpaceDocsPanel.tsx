import {
  ListChecksIcon,
  NotePencilIcon,
  PencilSimpleIcon,
  XIcon,
} from "@phosphor-icons/react";
import { ChannelDocumentConflictError } from "@posthog/api-client/posthog-client";
import {
  Badge,
  Button,
  Checkbox,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type {
  ChannelDocument,
  ChannelDocumentKind,
} from "@posthog/shared/domain-types";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useSpaceDocsPanelStore } from "@posthog/ui/features/space-docs/spaceDocsPanelStore";
import {
  useChannelDocumentMutations,
  useChannelDocuments,
} from "@posthog/ui/features/space-docs/useChannelDocuments";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useMemo, useState } from "react";
import type { Components } from "react-markdown";

const DOC_KIND_LABELS: Record<ChannelDocumentKind, string> = {
  todo: "Todo",
  plan: "Plan",
};

function docKindOf(document: ChannelDocument): ChannelDocumentKind {
  return document.doc_kind === "plan" ? "plan" : "todo";
}

/**
 * Interactive markdown for a todo doc: GFM task-list checkboxes become live
 * quill checkboxes. Checkboxes are counted in render order, which matches
 * source order, so the nth rendered box maps onto the nth `- [ ]` in the
 * markdown (code fences are skipped on both sides).
 */
function TodoMarkdown({
  content,
  disabled,
  onToggle,
}: {
  content: string;
  disabled: boolean;
  onToggle: (checkboxIndex: number) => void;
}) {
  const components = useMemo<Partial<Components>>(() => {
    let checkboxIndex = -1;
    return {
      input: ({ type, checked }) => {
        if (type !== "checkbox") return <input type={type} />;
        checkboxIndex++;
        const index = checkboxIndex;
        return (
          <Checkbox
            checked={Boolean(checked)}
            disabled={disabled}
            onCheckedChange={() => onToggle(index)}
            className="mr-1.5 align-middle"
          />
        );
      },
    };
  }, [disabled, onToggle]);
  return <MarkdownRenderer content={content} componentsOverride={components} />;
}

function DocumentBody({
  document,
  channelId,
}: {
  document: ChannelDocument;
  channelId: string;
}) {
  const { toggleCheckbox, isToggling, save, isSaving } =
    useChannelDocumentMutations(channelId);
  const { refetch } = useChannelDocuments(channelId, { enabled: false });
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [baseVersion, setBaseVersion] = useState(document.current_version);

  const startEditing = () => {
    setDraft(document.content);
    setBaseVersion(document.current_version);
    setEditing(true);
  };

  const handleToggle = async (checkboxIndex: number) => {
    const result = await toggleCheckbox({ document, checkboxIndex }).catch(
      (error: unknown) => {
        toast.error("Couldn't update the checkbox", {
          description: error instanceof Error ? error.message : String(error),
        });
        return null;
      },
    );
    if (result === "conflict" || result === "stale") {
      toast.error("This document just changed", {
        description: "It refreshed with the latest edits. Try again.",
      });
    }
  };

  const handleSave = async () => {
    try {
      await save({
        documentId: document.id,
        content: draft,
        expectedVersion: baseVersion,
      });
      setEditing(false);
    } catch (error) {
      if (error instanceof ChannelDocumentConflictError) {
        const { data } = await refetch();
        const fresh = data?.find((d) => d.id === document.id);
        if (fresh) setBaseVersion(fresh.current_version);
        toast.error("Someone else edited this document", {
          description:
            "Your text is still in the editor. Save again to replace the latest version.",
        });
        return;
      }
      toast.error("Couldn't save the document", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  if (editing) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="min-h-0 flex-1 resize-none rounded-md border border-border bg-transparent p-2 font-mono text-sm outline-none focus:border-primary"
          style={{ fontFamily: "var(--code-font-family)" }}
        />
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={isSaving}
            onClick={() => setEditing(false)}
          >
            Cancel
          </Button>
          <Button size="sm" disabled={isSaving} onClick={handleSave}>
            {isSaving ? <Spinner /> : null}
            Save
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <div className="group/doc">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="font-medium text-sm">{document.name}</span>
            <Badge variant="default">
              {DOC_KIND_LABELS[docKindOf(document)]}
            </Badge>
          </div>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="default"
                  size="icon-sm"
                  aria-label="Edit document"
                  onClick={startEditing}
                >
                  <PencilSimpleIcon size={14} />
                </Button>
              }
            />
            <TooltipContent>Edit as markdown</TooltipContent>
          </Tooltip>
        </div>
        {document.content.trim() ? (
          docKindOf(document) === "todo" ? (
            <TodoMarkdown
              content={document.content}
              disabled={isToggling}
              onToggle={handleToggle}
            />
          ) : (
            <MarkdownRenderer content={document.content} />
          )
        ) : (
          <p className="text-muted-foreground text-sm">
            Nothing here yet. Highlight text in a conversation to add the first
            item.
          </p>
        )}
      </div>
    </div>
  );
}

function PanelContent({ channelId }: { channelId: string }) {
  const { data: documents, isLoading } = useChannelDocuments(channelId);
  const { create, isCreating } = useChannelDocumentMutations(channelId);
  const focusDocKind = useSpaceDocsPanelStore((s) => s.focusDocKind);
  const [activeDocId, setActiveDocId] = useState<string | null>(null);

  const sorted = useMemo(() => {
    const list = documents ?? [];
    return [...list].sort((a, b) =>
      docKindOf(a) === docKindOf(b)
        ? a.name.localeCompare(b.name)
        : docKindOf(a) === "todo"
          ? -1
          : 1,
    );
  }, [documents]);

  // Follow the opener's intent: focus the doc of the captured kind once the
  // list is in, falling back to the first doc.
  useEffect(() => {
    if (sorted.length === 0) {
      setActiveDocId(null);
      return;
    }
    setActiveDocId((current) => {
      if (current && sorted.some((d) => d.id === current)) return current;
      const focused = focusDocKind
        ? sorted.find((d) => docKindOf(d) === focusDocKind)
        : undefined;
      return (focused ?? sorted[0])?.id ?? null;
    });
  }, [sorted, focusDocKind]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ListChecksIcon />
          </EmptyMedia>
          <EmptyTitle>No docs in this space yet</EmptyTitle>
          <EmptyDescription>
            Highlight text in a conversation to capture it here, or start an
            empty doc.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="default"
              disabled={isCreating}
              onClick={() => void create("todo")}
            >
              New todo list
            </Button>
            <Button
              variant="outline"
              size="default"
              disabled={isCreating}
              onClick={() => void create("plan")}
            >
              New plan
            </Button>
          </div>
        </EmptyContent>
      </Empty>
    );
  }

  const activeDoc = sorted.find((d) => d.id === activeDocId) ?? sorted[0];

  return (
    <>
      {sorted.length > 1 && (
        <div className="flex flex-wrap gap-1 border-border border-b px-3 py-2">
          {sorted.map((doc) => (
            <Button
              key={doc.id}
              variant={doc.id === activeDoc?.id ? "outline" : "default"}
              size="sm"
              onClick={() => setActiveDocId(doc.id)}
            >
              {docKindOf(doc) === "todo" ? (
                <ListChecksIcon size={14} />
              ) : (
                <NotePencilIcon size={14} />
              )}
              {doc.name}
            </Button>
          ))}
        </div>
      )}
      {activeDoc && (
        <DocumentBody
          key={activeDoc.id}
          document={activeDoc}
          channelId={channelId}
        />
      )}
    </>
  );
}

/**
 * The space docs sidepanel: a right dock pinned to one backend channel,
 * showing its shared todo/plan docs. Opened by message-selection captures (and
 * anything else calling `useSpaceDocsPanelStore.openPanel`).
 */
export function SpaceDocsPanel() {
  const open = useSpaceDocsPanelStore((s) => s.open);
  const width = useSpaceDocsPanelStore((s) => s.width);
  const isResizing = useSpaceDocsPanelStore((s) => s.isResizing);
  const channelId = useSpaceDocsPanelStore((s) => s.channelId);
  const closePanel = useSpaceDocsPanelStore((s) => s.closePanel);
  const setWidth = useSpaceDocsPanelStore((s) => s.setWidth);
  const setIsResizing = useSpaceDocsPanelStore((s) => s.setIsResizing);
  const { channels } = useTaskChannels();

  const channel = channels.find((c) => c.id === channelId);
  const channelLabel = channel
    ? channel.channel_type === "personal"
      ? "#me"
      : `#${channel.name}`
    : null;

  return (
    <ResizableSidebar
      open={open && Boolean(channelId)}
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="right"
    >
      <div className="flex h-full min-h-0 flex-col border-border border-l">
        <div className="flex h-8 shrink-0 items-center justify-between border-border border-b pr-1 pl-3">
          <span className="truncate font-medium text-sm">
            {channelLabel ? `${channelLabel} docs` : "Space docs"}
          </span>
          <Button
            variant="default"
            size="icon-sm"
            aria-label="Close docs panel"
            onClick={closePanel}
          >
            <XIcon size={14} />
          </Button>
        </div>
        {channelId && <PanelContent channelId={channelId} />}
      </div>
    </ResizableSidebar>
  );
}
