import { SpaceFileConflictError } from "@posthog/api-client/posthog-client";
import { buildSpaceFileTaskPrompt } from "@posthog/core/canvas/spaceFilePrompt";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { SpaceFileDocumentView } from "@posthog/ui/features/space-files/SpaceFileDocumentView";
import {
  useSpaceFile,
  useSpaceFileMutations,
} from "@posthog/ui/features/space-files/useSpaceFiles";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect, useRef, useState } from "react";

function browserSelection(): EditorSelection | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.toString().trim()) {
    return null;
  }
  const range = selection.getRangeAt(0);
  const selectionRoot =
    range.commonAncestorContainer instanceof Element
      ? range.commonAncestorContainer
      : range.commonAncestorContainer.parentElement;
  if (!selectionRoot?.closest("[data-space-file-preview]")) return null;
  const rect = range.getBoundingClientRect();
  if (!rect.width && !rect.height) return null;
  return {
    text: selection.toString(),
    fromLine: 1,
    toLine: selection.toString().split("\n").length,
    anchor: { top: rect.top, endX: rect.right, bottom: rect.bottom },
  };
}

export function SpaceFileDocument({ id }: { id: string | undefined }) {
  const { file, isLoading, isError, error, reload } = useSpaceFile(id);
  const { update, isUpdating } = useSpaceFileMutations();
  const { members } = useOrgMembers();
  const [sourceVisible, setSourceVisible] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [baseVersion, setBaseVersion] = useState(0);
  const [conflict, setConflict] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const openedFileId = useRef<string | null>(null);

  useEffect(() => {
    if (!file || file.id === openedFileId.current) return;
    openedFileId.current = file.id;
    setDraft(file.content);
    setBaseVersion(file.version);
    setConflict(false);
    setSaveError(null);
    track(ANALYTICS_EVENTS.SPACE_FILE_ACTION, {
      action_type: "open",
      file_id: file.id,
      channel_id: file.channel_id,
      success: true,
    });
  }, [file]);

  const save = async (): Promise<void> => {
    if (!file || isUpdating) return;
    setSaveError(null);
    try {
      const updated = await update(file.id, {
        content: draft,
        baseVersion,
      });
      setDraft(updated.content);
      setBaseVersion(updated.version);
      setConflict(false);
      setEditing(false);
      track(ANALYTICS_EVENTS.SPACE_FILE_ACTION, {
        action_type: "save",
        file_id: file.id,
        channel_id: file.channel_id,
        success: true,
      });
    } catch (cause) {
      const isConflict = cause instanceof SpaceFileConflictError;
      setConflict(isConflict);
      setSaveError(
        isConflict
          ? null
          : cause instanceof Error
            ? cause.message
            : "Couldn't save this file.",
      );
      track(ANALYTICS_EVENTS.SPACE_FILE_ACTION, {
        action_type: "save",
        file_id: file.id,
        channel_id: file.channel_id,
        success: false,
      });
    }
  };

  const reloadLatest = async (): Promise<void> => {
    const latest = await reload();
    if (latest) {
      setDraft(latest.content);
      setBaseVersion(latest.version);
    }
    setConflict(false);
    setSaveError(null);
  };
  const captureBrowserSelection = useCallback(() => {
    setSelection(browserSelection());
  }, []);
  useEffect(() => {
    if (sourceVisible) return;
    document.addEventListener("mouseup", captureBrowserSelection);
    return () =>
      document.removeEventListener("mouseup", captureBrowserSelection);
  }, [captureBrowserSelection, sourceVisible]);
  const openTaskForSelection = async (
    _start: number,
    _end: number,
    note: string,
  ): Promise<void> => {
    if (!file || !selection) return;
    openTaskInput({
      channelId: file.channel_id,
      initialPrompt: buildSpaceFileTaskPrompt({
        fileId: file.id,
        fileName: file.name,
        selectedText: selection.text,
        note,
      }),
    });
    track(ANALYTICS_EVENTS.SPACE_FILE_ACTION, {
      action_type: "task_draft_opened",
      file_id: file.id,
      channel_id: file.channel_id,
      success: true,
    });
  };

  const state = isLoading
    ? "loading"
    : isError
      ? "error"
      : file
        ? "document"
        : "empty";
  return (
    <>
      <SpaceFileDocumentView
        state={state}
        file={file}
        error={error}
        sourceVisible={sourceVisible}
        editing={editing}
        saving={isUpdating}
        draft={draft}
        conflict={conflict}
        saveError={saveError}
        onToggleSource={() => {
          setSelection(null);
          setSourceVisible((value) => !value);
        }}
        onEdit={() => {
          setSelection(null);
          if (file) setBaseVersion(file.version);
          setSourceVisible(true);
          setEditing(true);
        }}
        onCancel={() => {
          if (file) {
            setDraft(file.content);
            setBaseVersion(file.version);
          }
          setConflict(false);
          setSaveError(null);
          setEditing(false);
        }}
        onSave={() => void save()}
        onDraftChange={setDraft}
        onSelectionChange={setSelection}
        onReload={() => void reloadLatest()}
      />
      <SelectionCommentOverlay
        selection={selection}
        open={!!selection?.text.trim()}
        filePath={file?.name ?? "file.md"}
        actionLabel="Send to agent"
        placeholder="Add a note…"
        showActionText
        members={members}
        onDismiss={() => setSelection(null)}
        onSubmit={openTaskForSelection}
      />
    </>
  );
}
