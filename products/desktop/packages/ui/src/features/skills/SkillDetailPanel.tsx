import { DownloadSimpleIcon, WarningIcon } from "@phosphor-icons/react";
import type { SkillIssue } from "@posthog/core/skills/analyzeSkills";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenuCheckboxItem,
  DropdownMenuItem,
  DropdownMenuSeparator,
  Input,
} from "@posthog/quill";
import type { SkillInfo } from "@posthog/shared";
import { stripFrontmatter } from "@posthog/shared";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { toast } from "@posthog/ui/primitives/toast";
import { useState } from "react";
import { ReplaceSkillDialog } from "./ReplaceSkillDialog";
import { SOURCE_CONFIG } from "./SkillCard";
import { SkillFileEditor } from "./SkillFileEditor";
import { SkillFileTree } from "./SkillFileTree";
import { SkillManifestEditor } from "./SkillManifestEditor";
import { SkillChip, SkillPanelHeader } from "./SkillPanelHeader";
import { SkillBodySkeleton } from "./SkillSkeletons";
import { isSkillExistsError, skillErrorDescription } from "./skillErrors";
import { useSkillContents, useSkillFile } from "./useSkillContents";
import {
  useDeleteSkill,
  useDeleteSkillFile,
  useImportCodexSkill,
  useRenameSkillFile,
  useSaveSkillFile,
  useSaveSkillManifest,
} from "./useSkillMutations";
import { usePublishSkill } from "./useTeamSkillMutations";

interface SkillDetailPanelProps {
  skill: SkillInfo;
  onClose: () => void;
  issues?: SkillIssue[];
  /** Whether team skills are available for publishing. */
  canPublish?: boolean;
}

export function SkillDetailPanel({
  skill,
  onClose,
  issues = [],
  canPublish = false,
}: SkillDetailPanelProps) {
  const config = SOURCE_CONFIG[skill.source];

  const [selectedFile, setSelectedFile] = useState("SKILL.md");
  const [isEditing, setIsEditing] = useState(false);
  const [addFileOpen, setAddFileOpen] = useState(false);
  const [newFilePath, setNewFilePath] = useState("");
  const [renameFrom, setRenameFrom] = useState<string | null>(null);
  const [renameTo, setRenameTo] = useState("");
  const [deleteFileTarget, setDeleteFileTarget] = useState<string | null>(null);
  const [deleteSkillOpen, setDeleteSkillOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [confirmImportOverwrite, setConfirmImportOverwrite] = useState(false);

  const { data: contents } = useSkillContents(skill.path);
  const { data: fileContent, isLoading } = useSkillFile(
    skill.path,
    selectedFile,
  );

  const saveFile = useSaveSkillFile();
  const saveManifest = useSaveSkillManifest();
  const renameFile = useRenameSkillFile();
  const deleteFile = useDeleteSkillFile();
  const deleteSkill = useDeleteSkill();
  const publishSkill = usePublishSkill();
  const importCodexSkill = useImportCodexSkill();

  const files = contents?.files ?? [];
  const isSkillMd = selectedFile === "SKILL.md";
  const body = isSkillMd && fileContent ? stripFrontmatter(fileContent) : null;
  const isMarkdown = selectedFile.toLowerCase().endsWith(".md");
  const preview = isSkillMd ? body : fileContent;
  const canEditManifest = skill.editable && body !== null && !isEditing;

  const writeManifest = async (fields: {
    name?: string;
    description?: string;
    disableModelInvocation?: boolean;
  }) => {
    if (body === null) return;
    try {
      await saveManifest.mutateAsync({
        skillPath: skill.path,
        name: fields.name ?? skill.name,
        description: fields.description ?? skill.description,
        body,
        disableModelInvocation:
          fields.disableModelInvocation ??
          skill.disableModelInvocation ??
          false,
      });
    } catch (error) {
      toast.error("Failed to save the skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  const handleAddFile = async () => {
    const filePath = newFilePath.trim();
    if (!filePath) return;
    try {
      await saveFile.mutateAsync({
        skillPath: skill.path,
        filePath,
        content: "",
      });
      setAddFileOpen(false);
      setNewFilePath("");
      setSelectedFile(filePath);
      setIsEditing(true);
    } catch (error) {
      toast.error("Failed to add file", {
        description: skillErrorDescription(error),
      });
    }
  };

  const handleRenameFile = async () => {
    const toPath = renameTo.trim();
    if (!renameFrom || !toPath) return;
    try {
      await renameFile.mutateAsync({
        skillPath: skill.path,
        fromPath: renameFrom,
        toPath,
      });
      if (selectedFile === renameFrom) setSelectedFile(toPath);
      setRenameFrom(null);
    } catch (error) {
      toast.error("Failed to rename file", {
        description: skillErrorDescription(error),
      });
    }
  };

  const handleDeleteFile = async () => {
    if (!deleteFileTarget) return;
    try {
      await deleteFile.mutateAsync({
        skillPath: skill.path,
        filePath: deleteFileTarget,
      });
      if (selectedFile === deleteFileTarget) {
        setSelectedFile("SKILL.md");
        setIsEditing(false);
      }
      setDeleteFileTarget(null);
    } catch (error) {
      toast.error("Failed to delete file", {
        description: skillErrorDescription(error),
      });
    }
  };

  const handlePublish = async () => {
    try {
      const result = await publishSkill.mutateAsync({ skillPath: skill.path });
      setPublishOpen(false);
      toast.success(`Published ${skill.name} (v${result.version})`, {
        description:
          result.skipped.length > 0
            ? `Skipped ${result.skipped.length} binary/oversized file(s): ${result.skipped.join(", ")}`
            : "Teammates can now install it from the Team group",
      });
    } catch (error) {
      toast.error("Failed to publish skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  const handleImport = async (overwrite: boolean) => {
    try {
      await importCodexSkill.mutateAsync({
        skillPath: skill.path,
        overwrite,
      });
      setConfirmImportOverwrite(false);
      toast.success(`Imported ${skill.name}`, {
        description: "Now editable under Your skills",
      });
    } catch (error) {
      if (!overwrite && isSkillExistsError(error)) {
        setConfirmImportOverwrite(true);
        return;
      }
      toast.error("Failed to import skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  const handleDeleteSkill = async () => {
    try {
      await deleteSkill.mutateAsync({ skillPath: skill.path });
      setDeleteSkillOpen(false);
      onClose();
    } catch (error) {
      toast.error("Failed to delete skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <SkillPanelHeader
        name={skill.name}
        description={skill.description}
        onEdit={
          canEditManifest ? (fields) => void writeManifest(fields) : undefined
        }
        saving={saveManifest.isPending}
        onClose={onClose}
        actions={
          skill.source === "codex" ? (
            <Button
              type="button"
              variant="primary"
              size="sm"
              loading={importCodexSkill.isPending}
              disabled={importCodexSkill.isPending}
              onClick={() => void handleImport(false)}
            >
              <DownloadSimpleIcon size={12} />
              Import
            </Button>
          ) : null
        }
        menuItems={
          skill.editable && !isEditing ? (
            <>
              <DropdownMenuCheckboxItem
                checked={skill.disableModelInvocation ?? false}
                disabled={body === null}
                onCheckedChange={(checked: boolean) =>
                  void writeManifest({ disableModelInvocation: checked })
                }
              >
                Manual invocation only
              </DropdownMenuCheckboxItem>
              {canPublish ? (
                <DropdownMenuItem onClick={() => setPublishOpen(true)}>
                  Publish to team
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setDeleteSkillOpen(true)}>
                Delete skill
              </DropdownMenuItem>
            </>
          ) : null
        }
        badges={
          <>
            <SkillChip>
              <span
                className={`size-1.5 rounded-full ${config?.dotClass ?? "bg-gray-9"}`}
              />
              {config?.label ?? skill.source}
            </SkillChip>
            {skill.repoName ? <SkillChip>{skill.repoName}</SkillChip> : null}
            {skill.editable ? null : <SkillChip>Read-only</SkillChip>}
            {skill.disableModelInvocation ? (
              <SkillChip>Manual only</SkillChip>
            ) : null}
            {skill.enabled === false ? <SkillChip>Off</SkillChip> : null}
          </>
        }
      />

      <div className="max-h-[40%] shrink-0 overflow-y-auto border-gray-4 border-b">
        <SkillFileTree
          files={files}
          selectedPath={selectedFile}
          onSelect={(path) => {
            setSelectedFile(path);
            setIsEditing(false);
          }}
          onEditFile={
            skill.editable
              ? (path) => {
                  setSelectedFile(path);
                  setIsEditing(true);
                }
              : undefined
          }
          onRenameFile={
            skill.editable
              ? (path) => {
                  setRenameFrom(path);
                  setRenameTo(path);
                }
              : undefined
          }
          onDeleteFile={
            skill.editable ? (path) => setDeleteFileTarget(path) : undefined
          }
          onAddFile={skill.editable ? () => setAddFileOpen(true) : undefined}
        />
      </div>

      <div className="min-h-0 flex-1">
        {isEditing && isSkillMd ? (
          <SkillManifestEditor
            skill={skill}
            initialBody={body ?? ""}
            onCancel={() => setIsEditing(false)}
            onSaved={() => setIsEditing(false)}
          />
        ) : isEditing ? (
          <SkillFileEditor
            key={`${skill.path}/${selectedFile}`}
            skill={skill}
            filePath={selectedFile}
            initialContent={fileContent ?? ""}
            onCancel={() => setIsEditing(false)}
            onSaved={() => setIsEditing(false)}
          />
        ) : isMarkdown ? (
          <div className="flex h-full flex-col gap-2 overflow-y-auto px-3 py-2.5">
            {issues.map((issue) => (
              <div
                key={issue.type}
                className="flex items-start gap-1.5 rounded-md bg-amber-3 px-2 py-1.5 text-[12px] text-amber-11"
              >
                <WarningIcon size={13} className="mt-0.5 shrink-0" />
                {issue.message}
              </div>
            ))}
            {isLoading ? (
              <SkillBodySkeleton />
            ) : preview ? (
              <div className="text-[13px]">
                <MarkdownRenderer content={preview} />
              </div>
            ) : (
              <p className="text-[12px] text-gray-9">{selectedFile} is empty</p>
            )}
          </div>
        ) : isLoading ? (
          <SkillBodySkeleton />
        ) : fileContent != null ? (
          <CodeMirrorEditor
            content={fileContent}
            filePath={`${skill.path}/${selectedFile}`}
            readOnly
          />
        ) : (
          <p className="p-3 text-[12px] text-gray-9">
            Unable to display this file
          </p>
        )}
      </div>

      <Dialog open={addFileOpen} onOpenChange={setAddFileOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Add file</DialogTitle>
            <DialogDescription>
              Path relative to the skill directory
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            <Input
              autoFocus
              value={newFilePath}
              onChange={(event) => setNewFilePath(event.currentTarget.value)}
              placeholder="references/guide.md"
              aria-label="File path"
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleAddFile();
              }}
            />
          </DialogBody>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              Cancel
            </DialogClose>
            <Button
              type="button"
              variant="primary"
              onClick={() => void handleAddFile()}
              disabled={saveFile.isPending || !newFilePath.trim()}
            >
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameFrom !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setRenameFrom(null);
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Rename file</DialogTitle>
          </DialogHeader>
          <DialogBody>
            <Input
              autoFocus
              value={renameTo}
              aria-label="New file path"
              onChange={(event) => setRenameTo(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void handleRenameFile();
              }}
            />
          </DialogBody>
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              Cancel
            </DialogClose>
            <Button
              type="button"
              variant="primary"
              onClick={() => void handleRenameFile()}
              disabled={renameFile.isPending || !renameTo.trim()}
            >
              Rename
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleteFileTarget !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setDeleteFileTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete file</AlertDialogTitle>
            <AlertDialogDescription>
              Delete "{deleteFileTarget}" from this skill? This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteFileTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handleDeleteFile()}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ReplaceSkillDialog
        open={confirmImportOverwrite}
        onOpenChange={setConfirmImportOverwrite}
        skillName={skill.name}
        verb="Importing"
        onConfirm={() => void handleImport(true)}
      />

      <AlertDialog open={publishOpen} onOpenChange={setPublishOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Publish to team</AlertDialogTitle>
            <AlertDialogDescription>
              Publish "{skill.name}" to your team? Teammates will be able to
              view and install it. Re-publishing creates a new version.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPublishOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={publishSkill.isPending}
              disabled={publishSkill.isPending}
              onClick={() => void handlePublish()}
            >
              Publish
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteSkillOpen} onOpenChange={setDeleteSkillOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete skill</AlertDialogTitle>
            <AlertDialogDescription>
              Delete "{skill.name}" and all of its files? This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteSkillOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              loading={deleteSkill.isPending}
              disabled={deleteSkill.isPending}
              onClick={() => void handleDeleteSkill()}
            >
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
