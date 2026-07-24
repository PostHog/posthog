import { DownloadSimple, UsersThree, X } from "@phosphor-icons/react";
import type { TeamSkillInfo } from "@posthog/core/skills/teamSkillsService";
import { stripFrontmatter } from "@posthog/shared";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { toast } from "@posthog/ui/primitives/toast";
import {
  Badge,
  Box,
  Button,
  Flex,
  ScrollArea,
  Text,
  Tooltip,
} from "@radix-ui/themes";
import { useState } from "react";
import { ReplaceSkillDialog } from "./ReplaceSkillDialog";
import { SkillFileTree } from "./SkillFileTree";
import { isSkillExistsError, skillErrorDescription } from "./skillErrors";
import { useInstallTeamSkill } from "./useTeamSkillMutations";
import { useTeamSkillDetail, useTeamSkillFile } from "./useTeamSkills";

interface TeamSkillDetailPanelProps {
  skill: TeamSkillInfo;
  onClose: () => void;
}

/** Read-only view of a PostHog cloud team skill (body + companion files). */
export function TeamSkillDetailPanel({
  skill,
  onClose,
}: TeamSkillDetailPanelProps) {
  const [selectedFile, setSelectedFile] = useState("SKILL.md");
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const { data: detail, isLoading } = useTeamSkillDetail(skill.name);
  const isSkillMd = selectedFile === "SKILL.md";
  const { data: file, isLoading: isFileLoading } = useTeamSkillFile(
    skill.name,
    isSkillMd ? null : selectedFile,
  );
  const install = useInstallTeamSkill();

  const handleInstall = async (overwrite: boolean) => {
    try {
      await install.mutateAsync({ name: skill.name, overwrite });
      setConfirmOverwrite(false);
      toast.success(`Installed ${skill.name}`, {
        description: "Now available under Your skills",
      });
    } catch (error) {
      if (!overwrite && isSkillExistsError(error)) {
        setConfirmOverwrite(true);
        return;
      }
      toast.error("Failed to install skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  const treeFiles = [
    { path: "SKILL.md", size: detail?.body.length ?? 0 },
    ...(detail?.files ?? []).map((f) => ({ path: f.path, size: 0 })),
  ];

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
          <Tooltip content="Close">
            <button
              type="button"
              aria-label="Close"
              onClick={onClose}
              className="shrink-0 rounded p-0.5 text-gray-11 hover:bg-gray-3 hover:text-gray-12"
            >
              <X size={14} />
            </button>
          </Tooltip>
        </Flex>

        <Flex align="center" gap="2" wrap="wrap">
          <Badge size="1" variant="soft" color="gray">
            <UsersThree size={10} className="text-gray-9" />
            Team
          </Badge>
          <Badge size="1" variant="soft" color="gray">
            v{skill.version}
          </Badge>
          {skill.createdByEmail && (
            <Badge size="1" variant="soft" color="gray">
              {skill.createdByEmail}
            </Badge>
          )}
          {skill.installedLocally && (
            <Badge size="1" variant="soft" color="green">
              Installed
            </Badge>
          )}
          <Button
            size="1"
            variant="solid"
            onClick={() => void handleInstall(false)}
            disabled={install.isPending || isLoading}
          >
            <DownloadSimple size={12} />
            {skill.installedLocally ? "Reinstall" : "Install"}
          </Button>
        </Flex>
      </Flex>

      {treeFiles.length > 1 && (
        <Box className="max-h-[40%] shrink-0 overflow-y-auto border-b border-b-(--gray-5) py-1">
          <SkillFileTree
            files={treeFiles}
            selectedPath={selectedFile}
            onSelect={setSelectedFile}
          />
        </Box>
      )}

      <Box className="min-h-0 flex-1">
        {isSkillMd ? (
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
              ) : detail?.body ? (
                <Box className="rounded border border-gray-5 bg-gray-1 px-4 py-3 text-[13px]">
                  <MarkdownRenderer content={stripFrontmatter(detail.body)} />
                </Box>
              ) : (
                <Text className="text-[12px] text-gray-9">
                  No content in SKILL.md
                </Text>
              )}
            </Flex>
          </ScrollArea>
        ) : isFileLoading ? (
          <Box p="3">
            <Text className="text-[12px] text-gray-9">Loading...</Text>
          </Box>
        ) : file ? (
          <CodeMirrorEditor
            content={file.content}
            filePath={selectedFile}
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

      <ReplaceSkillDialog
        open={confirmOverwrite}
        onOpenChange={setConfirmOverwrite}
        skillName={skill.name}
        verb="Reinstalling"
        onConfirm={() => void handleInstall(true)}
      />
    </>
  );
}
