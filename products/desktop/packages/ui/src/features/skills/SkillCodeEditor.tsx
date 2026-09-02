import { EditorView } from "@codemirror/view";
import { useMemo, useRef } from "react";
import { useCodeMirror } from "../code-editor/hooks/useCodeMirror";
import { useEditorExtensions } from "../code-editor/hooks/useEditorExtensions";

interface SkillCodeEditorProps {
  /** Initial document; the editor is uncontrolled after mount. */
  initialContent: string;
  filePath?: string;
  onDocChanged: (doc: string) => void;
}

/** Editable CodeMirror for skill files. Reports edits via onDocChanged. */
export function SkillCodeEditor({
  initialContent,
  filePath,
  onDocChanged,
}: SkillCodeEditorProps) {
  const onDocChangedRef = useRef(onDocChanged);
  onDocChangedRef.current = onDocChanged;

  const baseExtensions = useEditorExtensions(filePath, false);
  const extensions = useMemo(
    () => [
      ...baseExtensions,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onDocChangedRef.current(update.state.doc.toString());
        }
      }),
    ],
    [baseExtensions],
  );

  const options = useMemo(
    () => ({ doc: initialContent, extensions, filePath }),
    [initialContent, extensions, filePath],
  );
  const { containerRef } = useCodeMirror(options);

  return <div ref={containerRef} className="h-full w-full" />;
}
