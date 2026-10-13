import { CheckIcon, PencilSimpleIcon, XIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useState } from "react";

const CLAMP_AT_CHARS = 190;

interface InlineEditProps {
  value: string;
  placeholder: string;
  ariaLabel: string;
  textClass: string;
  multiline?: boolean;
  clamp?: boolean;
  editable?: boolean;
  saving?: boolean;
  onSave: (value: string) => void;
}

export function InlineEdit({
  value,
  placeholder,
  ariaLabel,
  textClass,
  multiline,
  clamp,
  editable = true,
  saving,
  onSave,
}: InlineEditProps) {
  const [draft, setDraft] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  if (draft === null) {
    const isLong = clamp === true && value.length > CLAMP_AT_CHARS;
    const text = (
      <span
        className={`${isLong && !expanded ? "line-clamp-3" : "block"} ${
          value ? textClass : "text-[12px] text-gray-9 italic"
        }`}
      >
        {value || placeholder}
      </span>
    );

    return (
      <div className="flex min-w-0 flex-col items-start">
        {editable ? (
          <button
            type="button"
            aria-label={`Edit ${ariaLabel}`}
            className="group -mx-1 flex w-[calc(100%+0.5rem)] items-start gap-1 rounded px-1 py-0.5 text-left transition-colors hover:bg-gray-3"
            onClick={() => setDraft(value)}
          >
            <span className="min-w-0 flex-1">{text}</span>
            <PencilSimpleIcon
              size={11}
              className="mt-1 shrink-0 text-gray-9 opacity-0 transition-opacity group-hover:opacity-100"
            />
          </button>
        ) : value ? (
          <div className="min-w-0 py-0.5">{text}</div>
        ) : null}
        {isLong ? (
          <button
            type="button"
            className="py-0.5 text-[11px] text-gray-9 transition-colors hover:text-gray-11"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        ) : null}
      </div>
    );
  }

  const commit = () => {
    const next = draft.trim();
    setDraft(null);
    if (next !== value.trim()) onSave(next);
  };

  const fieldClass = `w-full rounded border border-accent-7 bg-gray-1 px-1.5 py-1 outline-none ${textClass}`;

  return (
    <div className="flex w-full flex-col gap-1">
      {multiline ? (
        <textarea
          // biome-ignore lint/a11y/noAutofocus: the field opens on an explicit click
          autoFocus
          rows={4}
          aria-label={ariaLabel}
          className={`${fieldClass} resize-none`}
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setDraft(null);
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              commit();
            }
          }}
        />
      ) : (
        <input
          // biome-ignore lint/a11y/noAutofocus: the field opens on an explicit click
          autoFocus
          aria-label={ariaLabel}
          className={fieldClass}
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setDraft(null);
            if (event.key === "Enter") commit();
          }}
        />
      )}
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="primary"
          size="icon-sm"
          aria-label={`Save ${ariaLabel}`}
          loading={saving}
          disabled={saving}
          onClick={commit}
        >
          <CheckIcon size={12} weight="bold" />
        </Button>
        <Button
          type="button"
          variant="link-muted"
          size="icon-sm"
          aria-label="Cancel"
          onClick={() => setDraft(null)}
        >
          <XIcon size={12} />
        </Button>
        <span className="text-[11px] text-gray-9">
          {multiline ? "⌘ + Enter saves" : "Enter saves"}, Esc cancels
        </span>
      </div>
    </div>
  );
}
