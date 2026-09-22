import { Button } from "@posthog/quill";
import type { SkillInfo } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
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

export function SkillManifestEditor({
  skill,
  initialBody,
  onCancel,
  onSaved,
}: SkillManifestEditorProps) {
  // Captured at mount: background refetches must not reset in-flight edits.
  const [mountedBody] = useState(initialBody);
  const bodyRef = useRef(mountedBody);
  const saveManifest = useSaveSkillManifest();

  const handleSave = async () => {
    try {
      await saveManifest.mutateAsync({
        skillPath: skill.path,
        name: skill.name,
        description: skill.description,
        body: bodyRef.current,
        disableModelInvocation: skill.disableModelInvocation ?? false,
      });
      onSaved();
    } catch (error) {
      toast.error("Failed to save skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <SkillCodeEditor
          initialContent={mountedBody}
          filePath={`${skill.path}/SKILL.md`}
          onDocChanged={(doc) => {
            bodyRef.current = doc;
          }}
        />
      </div>

      <div className="flex shrink-0 justify-end gap-1.5 border-gray-5 border-t p-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          size="sm"
          loading={saveManifest.isPending}
          disabled={saveManifest.isPending}
          onClick={() => void handleSave()}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
