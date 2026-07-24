import { useEffect, useRef, useState } from "react";

interface HeaderTitleEditorProps {
  initialTitle: string;
  onSubmit: (newTitle: string) => void;
  onCancel: () => void;
}

export function HeaderTitleEditor({
  initialTitle,
  onSubmit,
  onCancel,
}: HeaderTitleEditorProps) {
  const [editValue, setEditValue] = useState(initialTitle);
  const inputRef = useRef<HTMLInputElement>(null);
  const resolvedRef = useRef(false);

  useEffect(() => {
    const input = inputRef.current;
    if (input) {
      input.focus();
      input.select();
    }
  }, []);

  const handleSubmit = () => {
    if (resolvedRef.current) return;
    resolvedRef.current = true;
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== initialTitle) {
      onSubmit(trimmed);
    } else {
      onCancel();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      resolvedRef.current = true;
      onCancel();
    }
  };

  return (
    <input
      ref={inputRef}
      type="text"
      value={editValue}
      onChange={(e) => setEditValue(e.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={handleSubmit}
      className="no-drag h-5 min-w-0 flex-1 rounded-sm border border-accent-8 bg-gray-2 px-1 font-medium text-[12px] text-gray-12 outline-none"
    />
  );
}
