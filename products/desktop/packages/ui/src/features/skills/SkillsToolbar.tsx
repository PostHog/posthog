import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { Input } from "@posthog/quill";
import type { ReactNode, Ref } from "react";

export function SkillsToolbar({
  placeholder,
  value,
  onChange,
  inputRef,
  actions,
  filters,
}: {
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  inputRef?: Ref<HTMLInputElement>;
  actions?: ReactNode;
  filters?: ReactNode;
}) {
  return (
    <div className="shrink-0 border-gray-4 border-b">
      <div className="mx-auto w-full max-w-5xl px-4 pt-3">
        <div className={`flex items-center gap-2 ${filters ? "pb-2" : "pb-3"}`}>
          <div className="relative flex-1">
            <MagnifyingGlassIcon
              size={14}
              className="-translate-y-1/2 absolute top-1/2 left-2.5 text-gray-9"
            />
            <Input
              ref={inputRef}
              className="h-8 pl-7 text-[13px]"
              placeholder={placeholder}
              aria-label={placeholder}
              value={value}
              onChange={(event) => onChange(event.currentTarget.value)}
            />
          </div>
          {actions}
        </div>
        {filters ? (
          <div className="flex flex-wrap gap-1 pb-2.5">{filters}</div>
        ) : null}
      </div>
    </div>
  );
}
