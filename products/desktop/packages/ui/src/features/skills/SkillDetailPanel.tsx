import {
  CloudArrowUp,
  DownloadSimple,
  FilePlus,
  Folder,
  LockSimple,
  PencilSimple,
  Trash,
  Warning,
  X,
} from "@phosphor-icons/react";
import type { SkillIssue } from "@posthog/core/skills/analyzeSkills";
import type { SkillInfo } from "@posthog/shared";
import { stripFrontmatter } from "@posthog/shared";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { ExternalAppsOpener } from "@posthog/ui/features/task-detail/components/ExternalAppsOpener";
import { toast } from "@posthog/ui/primitives/toast";
import {
  AlertDialog,
  Badge,
  Box,
  Button,
  Callout,
  Dialog,
  Flex,
  ScrollArea,
  Text,
  TextField,
  Tooltip,
} from "@radix-ui/themes";
import { useState } from "react";
import { ReplaceSkillDialog } from "./ReplaceSkillDialog";
import { SOURCE_CONFIG } from "./SkillCard";
import { SkillFileEditor } from "./SkillFileEditor";
import { SkillFileTree } from "./SkillFileTree";
import { SkillManifestEditor } from "./SkillManifestEditor";
import { isSkillExistsError, skillErrorDescription } from "./skillErrors";
import { useSkillContents, useSkillFile } from "./useSkillContents";
import {
  useDeleteSkill,
  useDeleteSkillFile,
  useImportCodexSkill,
  useRenameSkillFile,
  useSaveSkillFile,
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
  const renameFile = useRenameSkillFile();
  const deleteFile = useDeleteSkillFile();
  const deleteSkill = useDeleteSkill();
  const publishSkill = usePublishSkill();
  const importCodexSkill = useImportCodexSkill();

  const files = contents?.files ?? [];
  const isSkillMd = selectedFile === "SKILL.md";
  const body = isSkillMd && fileContent ? stripFrontmatter(fileContent) : null;

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
    <>
      <Flex
        direction="column"
        gap="2"
        px="3"
        py="2"
        className="shrink-0 border-b border-b-(--gray-5)"
      >
        <Flex align="start" justify="between" gap="2">
          <Text className="block min-w-0 break-words font-medium text-[13px]">
            {skill.name}
          </Text>
          <Flex align="center" gap="1" className="shrink-0">
            {skill.editable && !isEditing && (
              <>
                {canPublish && (
                  <Tooltip content="Publish to team">
                    <button
                      type="button"
                      aria-label="Publish to team"
                      onClick={() => setPublishOpen(true)}
                      className="rounded p-0.5 text-gray-11 hover:bg-gray-3 hover:text-gray-12"
                    >
                      <CloudArrowUp size={14} />
                    </button>
                  </Tooltip>
                )}
                <Tooltip content="Edit skill">
                  <button
                    type="button"
                    aria-label="Edit skill"
                    onClick={() => setIsEditing(true)}
                    disabled={isLoading || fileContent == null}
                    className="rounded p-0.5 text-gray-11 hover:bg-gray-3 hover:text-gray-12"
                  >
                    <PencilSimple size={14} />
                  </button>
                </Tooltip>
                <Tooltip content="Add file">
                  <button
                    type="button"
                    aria-label="Add file"
                    onClick={() => setAddFileOpen(true)}
                    className="rounded p-0.5 text-gray-11 hover:bg-gray-3 hover:text-gray-12"
                  >
                    <FilePlus size={14} />
                  </button>
                </Tooltip>
                <Tooltip content="Delete skill">
                  <button
                    type="button"
                    aria-label="Delete skill"
                    onClick={() => setDeleteSkillOpen(true)}
                    className="rounded p-0.5 text-gray-11 hover:bg-gray-3 hover:text-red-11"
                  >
                    <Trash size={14} />
                  </button>
                </Tooltip>
              </>
            )}
            <Tooltip content="Close">
              <button
                type="button"
                aria-label="Close"
                onClick={onClose}
                className="rounded p-0.5 text-gray-11 hover:bg-gray-3 hover:text-gray-12"
              >
                <X size={14} />
              </button>
            </Tooltip>
          </Flex>
        </Flex>

        <Flex align="center" gap="2" wrap="wrap">
          <Badge size="1" variant="soft" color="gray">
            {config?.label ?? skill.source}
          </Badge>
          {skill.repoName && (
            <Badge size="1" variant="soft" color="gray">
              <Folder size={10} className="text-gray-9" />
              {skill.repoName}
            </Badge>
          )}
          {!skill.editable && (
            <Badge size="1" variant="soft" color="gray">
              <LockSimple size={10} className="text-gray-9" />
              Read-only
            </Badge>
          )}
          {skill.source === "codex" && (
            <Button
              size="1"
              variant="solid"
              onClick={() => void handleImport(false)}
              disabled={importCodexSkill.isPending}
            >
              <DownloadSimple size={12} />
              Import
            </Button>
          )}
          {skill.source !== "bundled" && (
            <ExternalAppsOpener targetPath={skill.path} />
          )}
        </Flex>

        {issues.length > 0 && (
          <Flex direction="column" gap="1">
            {issues.map((issue) => (
              <Callout.Root
                key={issue.type}
                size="1"
                color="amber"
                variant="surface"
              >
                <Callout.Icon>
                  <Warning size={12} />
                </Callout.Icon>
                <Callout.Text className="text-[12px]">
                  {issue.message}
                </Callout.Text>
              </Callout.Root>
            ))}
          </Flex>
        )}
      </Flex>

      {files.length > 1 && (
        <Box className="max-h-[40%] shrink-0 overflow-y-auto border-b border-b-(--gray-5) py-1">
          <SkillFileTree
            files={files}
            selectedPath={selectedFile}
            onSelect={(path) => {
              setSelectedFile(path);
              setIsEditing(false);
            }}
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
          />
        </Box>
      )}

      <Box className="min-h-0 flex-1">
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
        ) : isSkillMd ? (
          <ScrollArea
            type="auto"
            scrollbars="vertical"
            className="scroll-area-constrain-width h-full"
          >
            <Flex direction="column" gap="3" p="3">
              {skill.description && (
                <Text className="text-[12px] text-gray-10">
                  {skill.description}
                </Text>
              )}

              {isLoading ? (
                <Text className="text-[12px] text-gray-9">Loading...</Text>
              ) : body ? (
                <Box className="rounded border border-gray-5 bg-gray-1 px-4 py-3 text-[13px]">
                  <MarkdownRenderer content={body} />
                </Box>
              ) : (
                <Text className="text-[12px] text-gray-9">
                  No content in SKILL.md
                </Text>
              )}
            </Flex>
          </ScrollArea>
        ) : isLoading ? (
          <Box p="3">
            <Text className="text-[12px] text-gray-9">Loading...</Text>
          </Box>
        ) : fileContent != null ? (
          <CodeMirrorEditor
            content={fileContent}
            filePath={`${skill.path}/${selectedFile}`}
            relativePath={selectedFile}
            readOnly
          />
        ) : (
          <Box p="3">
            <Text className="text-[12px] text-gray-9">
              Unable to display this file
            </Text>
          </Box>
        )}
      </Box>

      <Dialog.Root open={addFileOpen} onOpenChange={setAddFileOpen}>
        <Dialog.Content maxWidth="380px" size="2">
          <Dialog.Title size="3">Add file</Dialog.Title>
          <Dialog.Description size="1" color="gray">
            Path relative to the skill directory
          </Dialog.Description>
          <Flex direction="column" gap="3" mt="3">
            <TextField.Root
              size="2"
              autoFocus
              value={newFilePath}
              onChange={(e) => setNewFilePath(e.target.value)}
              placeholder="references/guide.md"
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleAddFile();
              }}
            />
            <Flex justify="end" gap="2">
              <Dialog.Close>
                <Button size="1" variant="soft" color="gray">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button
                size="1"
                variant="solid"
                onClick={handleAddFile}
                disabled={saveFile.isPending || !newFilePath.trim()}
              >
                Add
              </Button>
            </Flex>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={renameFrom !== null}
        onOpenChange={(open) => {
          if (!open) setRenameFrom(null);
        }}
      >
        <Dialog.Content maxWidth="380px" size="2">
          <Dialog.Title size="3">Rename file</Dialog.Title>
          <Flex direction="column" gap="3" mt="3">
            <TextField.Root
              size="2"
              autoFocus
              value={renameTo}
              onChange={(e) => setRenameTo(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleRenameFile();
              }}
            />
            <Flex justify="end" gap="2">
              <Dialog.Close>
                <Button size="1" variant="soft" color="gray">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button
                size="1"
                variant="solid"
                onClick={handleRenameFile}
                disabled={renameFile.isPending || !renameTo.trim()}
              >
                Rename
              </Button>
            </Flex>
          </Flex>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root
        open={deleteFileTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteFileTarget(null);
        }}
      >
        <AlertDialog.Content maxWidth="420px" size="2">
          <AlertDialog.Title size="3">Delete file</AlertDialog.Title>
          <AlertDialog.Description size="1">
            Delete "{deleteFileTarget}" from this skill? This cannot be undone.
          </AlertDialog.Description>
          <Flex justify="end" gap="2" mt="4">
            <AlertDialog.Cancel>
              <Button size="1" variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                size="1"
                variant="solid"
                color="red"
                onClick={handleDeleteFile}
              >
                Delete
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>

      <ReplaceSkillDialog
        open={confirmImportOverwrite}
        onOpenChange={setConfirmImportOverwrite}
        skillName={skill.name}
        verb="Importing"
        onConfirm={() => void handleImport(true)}
      />

      <AlertDialog.Root open={publishOpen} onOpenChange={setPublishOpen}>
        <AlertDialog.Content maxWidth="420px" size="2">
          <AlertDialog.Title size="3">Publish to team</AlertDialog.Title>
          <AlertDialog.Description size="1">
            Publish "{skill.name}" to your team? Teammates will be able to view
            and install it. Re-publishing creates a new version.
          </AlertDialog.Description>
          <Flex justify="end" gap="2" mt="4">
            <AlertDialog.Cancel>
              <Button size="1" variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <Button
              size="1"
              variant="solid"
              onClick={handlePublish}
              disabled={publishSkill.isPending}
            >
              Publish
            </Button>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>

      <AlertDialog.Root
        open={deleteSkillOpen}
        onOpenChange={setDeleteSkillOpen}
      >
        <AlertDialog.Content maxWidth="420px" size="2">
          <AlertDialog.Title size="3">Delete skill</AlertDialog.Title>
          <AlertDialog.Description size="1">
            Delete "{skill.name}" and all of its files? This cannot be undone.
          </AlertDialog.Description>
          <Flex justify="end" gap="2" mt="4">
            <AlertDialog.Cancel>
              <Button size="1" variant="soft" color="gray">
                Cancel
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                size="1"
                variant="solid"
                color="red"
                onClick={handleDeleteSkill}
              >
                Delete
              </Button>
            </AlertDialog.Action>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </>
  );
}
