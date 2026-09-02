import { useCallback, useEffect, useRef } from "react";

const MAX_HEIGHT = 200;

interface InlineEditableTextProps {
  value: string;
  placeholder: string;
  active: boolean;
  onChange: (value: string) => void;
  onNavigateUp: () => void;
  onNavigateDown: () => void;
  onEscape: () => void;
  onSubmit: () => void;
}

function autosize(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  const next = Math.min(el.scrollHeight, MAX_HEIGHT);
  el.style.height = `${next}px`;
  // Only enable scrolling when content actually exceeds the cap. Leaving it
  // on "auto" surfaces a track on macOS when "Always show scrollbars" is set.
  el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? "auto" : "hidden";
}

export function InlineEditableText({
  value,
  placeholder,
  active,
  onChange,
  onNavigateUp,
  onNavigateDown,
  onEscape,
  onSubmit,
}: InlineEditableTextProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (el && active) {
      el.focus();
    }
  }, [active]);

  // Re-run on external value changes so the height tracks parent-driven
  // updates (e.g. clearing after submit). `value` isn't referenced in the
  // body — we read it via the DOM — so silence the exhaustive-deps lint.
  // biome-ignore lint/correctness/useExhaustiveDependencies: value drives autosize via the rendered DOM
  useEffect(() => {
    const el = textareaRef.current;
    if (el) autosize(el);
  }, [value]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onEscape();
      } else if (e.key === "ArrowUp") {
        const el = e.currentTarget;
        if (el.selectionStart === 0 && el.selectionEnd === 0) {
          e.preventDefault();
          onNavigateUp();
        }
      } else if (e.key === "ArrowDown") {
        const el = e.currentTarget;
        if (
          el.selectionStart === el.value.length &&
          el.selectionEnd === el.value.length
        ) {
          e.preventDefault();
          onNavigateDown();
        }
      } else if (e.key === "Tab") {
        e.preventDefault();
        onNavigateDown();
      } else if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        onSubmit();
      }
    },
    [onNavigateUp, onNavigateDown, onEscape, onSubmit],
  );

  return (
    <textarea
      ref={textareaRef}
      value={value}
      placeholder={placeholder}
      onChange={(e) => {
        onChange(e.target.value);
        autosize(e.target);
      }}
      onKeyDown={handleKeyDown}
      onClick={(e) => e.stopPropagation()}
      rows={1}
      className="block w-full cursor-text resize-none overflow-y-hidden break-words border-0 bg-transparent p-0 font-medium text-[13px] text-gray-12 leading-4 outline-none placeholder:text-gray-10 focus:outline-none"
      style={{
        userSelect: active ? "auto" : "none",
        pointerEvents: active ? "auto" : "none",
      }}
    />
  );
}
