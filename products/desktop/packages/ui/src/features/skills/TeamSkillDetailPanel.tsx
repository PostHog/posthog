import {
  DownloadSimpleIcon,
  FlowArrowIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import type { TeamSkillInfo } from "@posthog/core/skills/teamSkillsService";
import { Button } from "@posthog/quill";
import {
  AGENT_FLOW_SKILL_FILE,
  parseAgentFlowSkillFile,
  stripFrontmatter,
} from "@posthog/shared";
import { FlowSummary } from "@posthog/ui/features/agent-flows/FlowSummary";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { toast } from "@posthog/ui/primitives/toast";
import { useState } from "react";
import { ReplaceSkillDialog } from "./ReplaceSkillDialog";
import { SkillFileTree } from "./SkillFileTree";
import { SkillChip, SkillPanelHeader } from "./SkillPanelHeader";
import { SkillBodySkeleton } from "./SkillSkeletons";
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
  const [showFlowText, setShowFlowText] = useState(false);
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const { data: detail, isLoading } = useTeamSkillDetail(skill.name);
  const isSkillMd = selectedFile === "SKILL.md";
  const { data: file, isLoading: isFileLoading } = useTeamSkillFile(
    skill.name,
    isSkillMd ? null : selectedFile,
  );
  const hasFlowFile = (detail?.files ?? []).some(
    (item) => item.path === AGENT_FLOW_SKILL_FILE,
  );
  const { data: flowFile } = useTeamSkillFile(
    skill.name,
    hasFlowFile ? AGENT_FLOW_SKILL_FILE : null,
  );
  const flow = flowFile ? parseAgentFlowSkillFile(flowFile.content) : null;
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
    <div className="flex h-full min-h-0 flex-col">
      <SkillPanelHeader
        name={skill.name}
        description={skill.description || undefined}
        onClose={onClose}
        actions={
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={install.isPending || isLoading}
            loading={install.isPending}
            onClick={() => void handleInstall(false)}
          >
            <DownloadSimpleIcon size={12} />
            {skill.installedLocally ? "Reinstall" : "Install"}
          </Button>
        }
        badges={
          <>
            <SkillChip>
              <UsersThreeIcon size={10} />
              Team
            </SkillChip>
            <SkillChip>v{skill.version}</SkillChip>
            {flow ? (
              <SkillChip>
                <FlowArrowIcon size={10} />
                {flow.steps.length}-step flow
              </SkillChip>
            ) : null}
            {skill.createdByEmail ? (
              <SkillChip>{skill.createdByEmail}</SkillChip>
            ) : null}
            {skill.installedLocally ? (
              <SkillChip tone="positive">Installed</SkillChip>
            ) : null}
          </>
        }
      />

      {treeFiles.length > 1 ? (
        <div className="max-h-[40%] shrink-0 overflow-y-auto border-gray-4 border-b">
          <SkillFileTree
            files={treeFiles}
            selectedPath={selectedFile}
            onSelect={setSelectedFile}
          />
        </div>
      ) : null}

      <div className="min-h-0 flex-1">
        {isSkillMd ? (
          <div className="flex h-full flex-col gap-2 overflow-y-auto px-3 py-2.5">
            {isLoading ? (
              <SkillBodySkeleton />
            ) : flow && !showFlowText ? (
              <>
                <FlowSummary flow={flow} />
                <button
                  type="button"
                  className="self-start text-[12px] text-gray-10 underline-offset-2 hover:underline"
                  onClick={() => setShowFlowText(true)}
                >
                  Show SKILL.md text
                </button>
              </>
            ) : detail?.body ? (
              <>
                <div className="text-[13px]">
                  <MarkdownRenderer content={stripFrontmatter(detail.body)} />
                </div>
                {flow ? (
                  <button
                    type="button"
                    className="self-start text-[12px] text-gray-10 underline-offset-2 hover:underline"
                    onClick={() => setShowFlowText(false)}
                  >
                    Show the flow steps
                  </button>
                ) : null}
              </>
            ) : (
              <p className="text-[12px] text-gray-9">No content in SKILL.md</p>
            )}
          </div>
        ) : isFileLoading ? (
          <SkillBodySkeleton />
        ) : file && selectedFile.toLowerCase().endsWith(".md") ? (
          <div className="h-full overflow-y-auto px-3 py-2.5 text-[13px]">
            <MarkdownRenderer content={file.content} />
          </div>
        ) : file ? (
          <CodeMirrorEditor
            content={file.content}
            filePath={selectedFile}
            readOnly
          />
        ) : (
          <p className="p-3 text-[12px] text-gray-9">
            Unable to display this file
          </p>
        )}
      </div>

      <ReplaceSkillDialog
        open={confirmOverwrite}
        onOpenChange={setConfirmOverwrite}
        skillName={skill.name}
        verb="Reinstalling"
        onConfirm={() => void handleInstall(true)}
      />
    </div>
  );
}
