import { Button } from "@posthog/quill";
import type { SkillInfo } from "@posthog/shared";
import { toast } from "@posthog/ui/primitives/toast";
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
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <SkillCodeEditor
          initialContent={mountedContent}
          filePath={`${skill.path}/${filePath}`}
          onDocChanged={(doc) => {
            contentRef.current = doc;
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
          loading={saveFile.isPending}
          disabled={saveFile.isPending}
          onClick={() => void handleSave()}
        >
          Save
        </Button>
      </div>
    </div>
  );
}
