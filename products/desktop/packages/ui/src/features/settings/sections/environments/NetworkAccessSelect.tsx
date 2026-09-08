import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Text,
} from "@posthog/quill";
import type { NetworkAccessLevel } from "@posthog/shared/domain-types";

const NETWORK_ACCESS_OPTIONS: {
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

function optionOf(value: NetworkAccessLevel) {
  return (
    NETWORK_ACCESS_OPTIONS.find((option) => option.value === value) ??
    NETWORK_ACCESS_OPTIONS[0]
  );
}

/** The two lines every option shows: its name, then what it allows. */
function OptionBody({
  label,
  description,
  selected,
}: {
  label: string;
  description: string;
  selected?: boolean;
}) {
  return (
    <span className="flex flex-col text-left">
      <Text
        className={`text-(--gray-12) text-[12.5px] ${selected ? "font-medium" : ""}`}
      >
        {label}
      </Text>
      <Text className="whitespace-normal text-(--gray-11) text-[11.5px]">
        {description}
      </Text>
    </span>
  );
}

interface NetworkAccessSelectProps {
  value: NetworkAccessLevel;
  onChange: (value: NetworkAccessLevel) => void;
}

/** Which hosts a sandbox may reach, with each level's effect under its name. */
export function NetworkAccessSelect({
  value,
  onChange,
}: NetworkAccessSelectProps) {
  return (
    <Select
      value={value}
      onValueChange={(next: NetworkAccessLevel | null) => {
        if (next !== null) onChange(next);
      }}
      items={NETWORK_ACCESS_OPTIONS.map((option) => ({
        value: option.value,
        label: option.label,
      }))}
    >
      <SelectTrigger aria-label="Network access" className="w-full">
        <SelectValue>
          {(selected: NetworkAccessLevel) => (
            <OptionBody
              label={optionOf(selected).label}
              description={optionOf(selected).description}
            />
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent align="start" side="bottom" sideOffset={6}>
        {NETWORK_ACCESS_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            <OptionBody
              label={option.label}
              description={option.description}
              selected={option.value === value}
            />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
