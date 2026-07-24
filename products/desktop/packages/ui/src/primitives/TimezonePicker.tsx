import { CaretDown } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import { useRef, useState } from "react";
import {
  formatTimezoneLabel,
  isValidTimezone,
  type TimezoneOption,
  timezoneOptions,
} from "./timezone";

interface TimezonePickerProps {
  value: string;
  onValueChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
  size?: "sm" | "default" | "lg";
}

export function TimezonePicker({
  value,
  onValueChange,
  disabled,
  className,
  size = "sm",
}: TimezonePickerProps) {
  const options = timezoneOptions();
  const selectedOption =
    options.find((option) => option.value === value) ?? null;
  const anchorRef = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState("");
  const customTimezone = search.trim();
  const canUseCustomTimezone =
    customTimezone !== "" &&
    !options.some((option) => option.value === customTimezone) &&
    isValidTimezone(customTimezone);

  return (
    <div ref={anchorRef} className={className}>
      <Combobox<TimezoneOption>
        items={options}
        value={selectedOption}
        disabled={disabled}
        onValueChange={(option) => {
          if (option) {
            onValueChange(option.value);
            setSearch("");
          }
        }}
        inputValue={search}
        onInputValueChange={(next) => setSearch(next ?? "")}
      >
        <ComboboxTrigger
          render={
            <Button
              type="button"
              variant="outline"
              size={size}
              disabled={disabled}
              aria-label="Schedule timezone"
              className={`w-full justify-between ${
                size === "sm" ? "" : "text-[13px]"
              }`}
            >
              <span className="min-w-0 truncate text-left">
                {selectedOption?.label ?? value}
              </span>
              <CaretDown
                size={10}
                weight="bold"
                className="shrink-0 text-muted-foreground"
              />
            </Button>
          }
        />
        <ComboboxContent
          anchor={anchorRef}
          side="bottom"
          sideOffset={4}
          align="start"
          className="w-[320px] max-w-[calc(100vw-2rem)]"
        >
          <ComboboxInput
            placeholder="Search timezones..."
            showTrigger={false}
          />
          <ComboboxEmpty>
            {canUseCustomTimezone ? (
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={() => {
                  onValueChange(customTimezone);
                  setSearch("");
                }}
              >
                Use {formatTimezoneLabel(customTimezone)}
              </Button>
            ) : (
              "No timezones found."
            )}
          </ComboboxEmpty>
          <ComboboxList className="max-h-[240px]">
            {(option: TimezoneOption) => (
              <ComboboxItem
                key={option.value}
                value={option}
                title={option.label}
              >
                {option.label}
              </ComboboxItem>
            )}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    </div>
  );
}
