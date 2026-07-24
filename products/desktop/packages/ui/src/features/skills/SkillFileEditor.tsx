import type { SkillInfo } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
import { Box, Button, Flex } from "@radix-ui/themes";
import { useRef, useState } from "react";
import { SkillCodeEditor } from "./SkillCodeEditor";
import { skillErrorDescription } from "./skillErrors";
import { useSaveSkillFile } from "./useSkillMutations";

interface SkillFileEditorProps {
  skill: SkillInfo;
  filePath: string;
  initialContent: string;
  onCancel: () => void;
  onSaved: () => void;
}

/** Edit mode for a companion file inside a skill directory. */
export function SkillFileEditor({
  skill,
  filePath,
  initialContent,
  onCancel,
  onSaved,
}: SkillFileEditorProps) {
  // Captured at mount: background refetches must not reset in-flight edits.
  const [mountedContent] = useState(initialContent);
  const contentRef = useRef(mountedContent);
  const saveFile = useSaveSkillFile();

  const handleSave = async () => {
    try {
      await saveFile.mutateAsync({
        skillPath: skill.path,
        filePath,
        content: contentRef.current,
      });
      onSaved();
    } catch (error) {
      toast.error("Failed to save file", {
        description: skillErrorDescription(error),
      });
    }
  };

  return (
    <Flex direction="column" height="100%">
      <Box className="min-h-0 flex-1">
        <SkillCodeEditor
          initialContent={mountedContent}
          filePath={`${skill.path}/${filePath}`}
          onDocChanged={(doc) => {
            contentRef.current = doc;
          }}
        />
      </Box>
      <Flex
        justify="end"
        gap="2"
        p="2"
        className="shrink-0 border-t border-t-(--gray-5)"
      >
        <Button size="1" variant="soft" color="gray" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          size="1"
          variant="solid"
          onClick={handleSave}
          disabled={saveFile.isPending}
        >
          Save
        </Button>
      </Flex>
    </Flex>
  );
}
