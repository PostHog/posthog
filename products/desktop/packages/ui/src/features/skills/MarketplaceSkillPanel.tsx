import { DownloadSimple, Warning, X } from "@phosphor-icons/react";
import { stripFrontmatter } from "@posthog/shared";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { toast } from "@posthog/ui/primitives/toast";
import {
  Badge,
  Box,
  Button,
  Callout,
  Flex,
  ScrollArea,
  Text,
  Tooltip,
} from "@radix-ui/themes";
import { useState } from "react";
import { ReplaceSkillDialog } from "./ReplaceSkillDialog";
import { SkillFileTree } from "./SkillFileTree";
import { isSkillExistsError, skillErrorDescription } from "./skillErrors";
import {
  installsFormatter,
  type MarketplaceSkillSummary,
  useInstallMarketplaceSkill,
  useMarketplacePreview,
} from "./useMarketplace";

interface MarketplaceSkillPanelProps {
  result: MarketplaceSkillSummary;
  onClose: () => void;
}

/**
 * Pre-install preview: every file in the skill is visible before anything
 * touches disk. Installing a skill is installing code an agent will run.
 */
export function MarketplaceSkillPanel({
  result,
  onClose,
}: MarketplaceSkillPanelProps) {
  const [selectedFile, setSelectedFile] = useState("SKILL.md");
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const { data: preview, isLoading } = useMarketplacePreview({
    source: result.source,
    skillId: result.skillId,
  });
  const install = useInstallMarketplaceSkill();

  const files = preview?.files ?? [];
  const selected = files.find((f) => f.path === selectedFile);
  const isSkillMd = selectedFile === "SKILL.md";

  const handleInstall = async (overwrite: boolean) => {
    try {
      await install.mutateAsync({
        source: result.source,
        skillId: result.skillId,
        overwrite,
      });
      setConfirmOverwrite(false);
      toast.success(`Installed ${result.name}`, {
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
            {result.name}
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
            {result.source}
          </Badge>
          <Badge size="1" variant="soft" color="gray">
            {installsFormatter.format(result.installs)} installs
          </Badge>
          {result.installed && (
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
            {result.installed ? "Reinstall" : "Install"}
          </Button>
        </Flex>

        {preview?.hasScripts && (
          <Callout.Root size="1" color="amber" variant="surface">
            <Callout.Icon>
              <Warning size={12} />
            </Callout.Icon>
            <Callout.Text className="text-[12px]">
              This skill contains scripts that agents can execute. Review every
              file before installing.
            </Callout.Text>
          </Callout.Root>
        )}
      </Flex>

      {files.length > 1 && (
        <Box className="max-h-[40%] shrink-0 overflow-y-auto border-b border-b-(--gray-5) py-1">
          <SkillFileTree
            files={files.map((f) => ({ path: f.path, size: f.size }))}
            selectedPath={selectedFile}
            onSelect={setSelectedFile}
          />
        </Box>
      )}

      <Box className="min-h-0 flex-1">
        {isLoading ? (
          <Box p="3">
            <Text className="text-[12px] text-gray-9">Loading...</Text>
          </Box>
        ) : selected?.content == null ? (
          <Box p="3">
            <Text className="text-[12px] text-gray-9">
              {selected
                ? "Unable to display this file"
                : "No content to preview"}
            </Text>
          </Box>
        ) : isSkillMd ? (
          <ScrollArea
            type="auto"
            scrollbars="vertical"
            className="scroll-area-constrain-width h-full"
          >
            <Box p="3">
              <Box className="rounded border border-gray-5 bg-gray-1 px-4 py-3 text-[13px]">
                <MarkdownRenderer
                  content={stripFrontmatter(selected.content)}
                />
              </Box>
            </Box>
          </ScrollArea>
        ) : (
          <CodeMirrorEditor
            content={selected.content}
            filePath={selectedFile}
            relativePath={selectedFile}
            readOnly
          />
        )}
      </Box>

      <ReplaceSkillDialog
        open={confirmOverwrite}
        onOpenChange={setConfirmOverwrite}
        skillName={result.skillId}
        verb="Reinstalling"
        onConfirm={() => void handleInstall(true)}
      />
    </>
  );
}
