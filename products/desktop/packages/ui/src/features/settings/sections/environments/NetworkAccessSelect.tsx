import { CaretDown } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";
import type { NetworkAccessLevel } from "@posthog/shared/domain-types";
import { useState } from "react";

export const NETWORK_ACCESS_OPTIONS: {
  value: NetworkAccessLevel;
  label: string;
  description: string;
}[] = [
  {
    value: "trusted",
    label: "Trusted",
    description: "Downloads packages from verified sources",
  },
  {
    value: "full",
    label: "Full",
    description: "Unrestricted internet access",
  },
  {
    value: "custom",
    label: "Custom",
    description: "Create a list of allowed domains",
  },
];

interface NetworkAccessSelectProps {
  value: NetworkAccessLevel;
  onChange: (value: NetworkAccessLevel) => void;
}

/** Which hosts a sandbox may reach, with each level's effect under its name. */
export function NetworkAccessSelect({
  value,
  onChange,
}: NetworkAccessSelectProps) {
  const [open, setOpen] = useState(false);
  const current =
    NETWORK_ACCESS_OPTIONS.find((option) => option.value === value) ??
    NETWORK_ACCESS_OPTIONS[0];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="Network access"
        className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-(--radius-2) border border-(--gray-6) bg-transparent px-3 py-2 text-left transition-colors hover:border-(--gray-8)"
      >
        <span className="flex flex-col">
          <Text className="text-(--gray-12) text-[12.5px]">
            {current.label}
          </Text>
          <Text className="text-(--gray-11) text-[11.5px]">
            {current.description}
          </Text>
        </span>
        <CaretDown
          size={12}
          className={`shrink-0 text-(--gray-10) transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-(--color-panel-solid) shadow-lg">
          {NETWORK_ACCESS_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
              className="flex w-full cursor-pointer flex-col border-0 bg-transparent px-3 py-2 text-left transition-colors hover:bg-(--gray-3) data-[active]:bg-(--accent-4) motion-reduce:transition-none"
              data-active={option.value === value || undefined}
            >
              <Text
                className={`text-(--gray-12) text-[12.5px] ${option.value === value ? "font-medium" : ""}`}
              >
                {option.label}
              </Text>
              <Text className="text-(--gray-11) text-[11.5px]">
                {option.description}
              </Text>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
