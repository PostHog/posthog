import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";

export interface SettingsSelectOption {
  value: string | null;
  label: string;
  description?: string;
  disabled?: boolean;
}

export function SettingsSelect({
  value,
  options,
  onChange,
  ariaLabel,
  placeholder,
}: {
  value: string | null;
  options: SettingsSelectOption[];
  onChange: (value: string | null) => void;
  ariaLabel: string;
  placeholder?: string;
}) {
  return (
    <Select
      value={value}
      onValueChange={(next: string | null) => onChange(next)}
      items={options.map((o) => ({ value: o.value, label: o.label }))}
    >
      <SelectTrigger size="sm" aria-label={ariaLabel} className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent align="start" side="bottom" sideOffset={6}>
        {options.map((option) => (
          <SelectItem
            key={option.value ?? "__default__"}
            value={option.value}
            disabled={option.disabled}
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
