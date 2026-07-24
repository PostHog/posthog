import type { SkillInfo } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
import { Box, Button, Flex, Text, TextArea, TextField } from "@radix-ui/themes";
import { useRef, useState } from "react";
import { SkillCodeEditor } from "./SkillCodeEditor";
import { skillErrorDescription } from "./skillErrors";
import { useSaveSkillManifest } from "./useSkillMutations";

interface SkillManifestEditorProps {
  skill: SkillInfo;
  initialBody: string;
  onCancel: () => void;
  onSaved: () => void;
}

/**
 * Edit mode for SKILL.md: a small form for the frontmatter (users never
 * hand-edit YAML) plus a markdown editor for the body.
 */
export function SkillManifestEditor({
  skill,
  initialBody,
  onCancel,
  onSaved,
}: SkillManifestEditorProps) {
  const [name, setName] = useState(skill.name);
  const [description, setDescription] = useState(skill.description);
  // Captured at mount: background refetches must not reset in-flight edits.
  const [mountedBody] = useState(initialBody);
  const bodyRef = useRef(mountedBody);
  const saveManifest = useSaveSkillManifest();

  const handleSave = async () => {
    try {
      await saveManifest.mutateAsync({
        skillPath: skill.path,
        name,
        description,
        body: bodyRef.current,
      });
      onSaved();
    } catch (error) {
      toast.error("Failed to save skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  return (
    <Flex direction="column" height="100%">
      <Flex direction="column" gap="2" p="3" className="shrink-0">
        <Box>
          <Text as="label" className="mb-1 block text-[12px] text-gray-10">
            Name
          </Text>
          <TextField.Root
            size="1"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="skill-name"
          />
        </Box>
        <Box>
          <Text as="label" className="mb-1 block text-[12px] text-gray-10">
            Description
          </Text>
          <TextArea
            size="1"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="When should an agent use this skill?"
          />
        </Box>
      </Flex>

      <Box className="min-h-0 flex-1 border-t border-t-(--gray-5)">
        <SkillCodeEditor
          initialContent={mountedBody}
          filePath={`${skill.path}/SKILL.md`}
          onDocChanged={(doc) => {
            bodyRef.current = doc;
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
          disabled={saveManifest.isPending || !name.trim()}
        >
          Save
        </Button>
      </Flex>
    </Flex>
  );
}
