import { FileTextIcon } from "@phosphor-icons/react";
import type { SpaceFile } from "@posthog/api-client/posthog-client";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import {
  CodeMirrorEditor,
  type EditorSelection,
} from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { DocumentPreviewHeader } from "@posthog/ui/features/code-editor/components/DocumentPreviewHeader";
import { MarkdownDocumentPreview } from "@posthog/ui/features/code-editor/components/MarkdownDocumentPreview";
import { OpenSidebarButton } from "@posthog/ui/features/sidebar/components/OpenSidebarButton";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import type { ReactElement } from "react";

export type SpaceFileDocumentState = "loading" | "error" | "empty" | "document";

export function SpaceFileDocumentView({
  state,
  file,
  error,
  sourceVisible,
  editing,
  saving,
  draft,
  conflict,
  saveError,
  onToggleSource,
  onEdit,
  onCancel,
  onSave,
  onDraftChange,
  onSelectionChange,
  onReload,
}: {
  state: SpaceFileDocumentState;
  file?: SpaceFile;
  error?: Error | null;
  sourceVisible: boolean;
  editing: boolean;
  saving: boolean;
  draft: string;
  conflict: boolean;
  saveError: string | null;
  onToggleSource: () => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onDraftChange: (content: string) => void;
  onSelectionChange: (selection: EditorSelection) => void;
  onReload: () => void;
}): ReactElement {
  if (state === "loading") {
    return <LoadingState className="h-full" label="Loading file" />;
  }

  if (state !== "document" || !file) {
    const content =
      state === "error"
        ? ["Couldn't load file", error?.message ?? "Try again shortly."]
        : ["Pick a file", "Choose a file from the list to open it here."];
    return (
      <div className="flex h-full items-center justify-center p-6">
        <Empty className="border-0">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FileTextIcon />
            </EmptyMedia>
            <EmptyTitle>{content[0]}</EmptyTitle>
            {content[1] && <EmptyDescription>{content[1]}</EmptyDescription>}
          </EmptyHeader>
          {state === "empty" && (
            <EmptyContent>
              <OpenSidebarButton />
            </EmptyContent>
          )}
          {state === "error" && (
            <EmptyContent>
              <Button variant="outline" onClick={onReload}>
                Try again
              </Button>
            </EmptyContent>
          )}
        </Empty>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <DocumentPreviewHeader
        label={file.name}
        content={file.content}
        getContent={() => draft}
        showRendered={!sourceVisible}
        onToggleRendered={onToggleSource}
        canEdit
        editing={editing}
        saving={saving}
        onEdit={onEdit}
        onCancel={onCancel}
        onSave={onSave}
      />
      {conflict && (
        <div className="flex shrink-0 items-center justify-between gap-3 border-border border-b bg-warning/10 px-3 py-2 text-sm">
          <span>
            This file changed elsewhere. Your draft is still available.
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={saving}
            onClick={onReload}
          >
            Reload latest
          </Button>
        </div>
      )}
      {saveError && (
        <div className="shrink-0 border-border border-b bg-destructive/10 px-3 py-2 text-destructive text-sm">
          Couldn't save this file. Your draft is still available. Try again.
        </div>
      )}
      {sourceVisible ? (
        <div className="min-h-0 flex-1">
          <CodeMirrorEditor
            key={`${file.id}:${editing ? "edit" : "source"}`}
            content={editing ? draft : file.content}
            filePath={`space-files/${file.id}/${file.name}`}
            readOnly={!editing}
            enrichment={undefined}
            onContentChange={onDraftChange}
            onSelectionChange={onSelectionChange}
          />
        </div>
      ) : (
        <div
          data-space-file-preview=""
          className="min-h-0 flex-1 overflow-y-auto"
        >
          <MarkdownDocumentPreview content={file.content} />
        </div>
      )}
    </div>
  );
}
