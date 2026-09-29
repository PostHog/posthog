import { FunnelSimpleIcon } from "@phosphor-icons/react";
import {
  Button,
  Combobox,
  ComboboxCollection,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  cn,
  DropdownMenuCheckboxItem,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { type ReactElement, type ReactNode, useState } from "react";

export interface FilterOption<Value extends string> {
  value: Value;
  label: string;
  searchLabel?: string;
  icon?: ReactNode;
}

/**
 * The parts every list-filter menu is built from. Canvases, Activity and
 * Self-driving all draw them, so they live here rather than per feature.
 */
export function FilterMenuTrigger({
  active,
  label,
  dataAttr,
  size = "icon-sm",
}: {
  active: boolean;
  label: string;
  dataAttr: string;
  size?: "icon-xs" | "icon-sm";
}): ReactElement {
  return (
    <DropdownMenuTrigger
      render={
        <Button
          variant="default"
          size={size}
          aria-label={label}
          data-attr={dataAttr}
          className="relative"
        >
          <FunnelSimpleIcon />
          {active && (
            <span
              aria-hidden
              className="absolute top-0 right-0 size-1.5 rounded-full bg-primary"
            />
          )}
        </Button>
      }
    />
  );
}

export function FilterSubMenuTrigger({
  label,
  value,
  active,
  disabled,
}: {
  label: string;
  value: string;
  active: boolean;
  disabled?: boolean;
}): ReactElement {
  return (
    <DropdownMenuSubTrigger className="pr-1" disabled={disabled}>
      <span>{label}</span>
      <span
        title={value}
        className={cn(
          "min-w-0 flex-1 truncate pl-4 text-right",
          active ? "text-primary" : "text-muted-foreground/80",
        )}
      >
        {value}
      </span>
    </DropdownMenuSubTrigger>
  );
}

export function FilterSubMenu({
  label,
  value,
  active,
  children,
}: {
  label: string;
  value: string;
  active: boolean;
  children: ReactNode;
}): ReactElement {
  return (
    <DropdownMenuSub>
      <FilterSubMenuTrigger label={label} value={value} active={active} />
      <DropdownMenuSubContent side="right" sideOffset={4}>
        {children}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

export function FilterRadioSubMenu<Value extends string>({
  label,
  options,
  value,
  defaultValue,
  valueLabel,
  onChange,
  searchPlaceholder,
}: {
  label: string;
  options: readonly FilterOption<Value>[];
  value: Value;
  defaultValue: Value;
  /** Overrides the option's own label, for a value the list cannot name. */
  valueLabel?: string;
  onChange: (value: Value) => void;
  searchPlaceholder?: string;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const [autoFocusSearch, setAutoFocusSearch] = useState(false);
  const [search, setSearch] = useState("");
  const selected =
    valueLabel ?? options.find((option) => option.value === value)?.label ?? "";

  if (searchPlaceholder) {
    return (
      <DropdownMenuSub
        open={open}
        onOpenChange={(next, details) => {
          setAutoFocusSearch(next && details.event.type === "keydown");
          setOpen(next);
          setSearch("");
        }}
      >
        <FilterSubMenuTrigger
          label={label}
          value={selected}
          active={value !== defaultValue}
        />
        <DropdownMenuSubContent className="w-64 [&>div]:overflow-hidden [&>div]:p-0">
          <Combobox<FilterOption<Value>>
            inline
            autoHighlight
            items={options}
            limit={20}
            inputValue={search}
            onInputValueChange={(next, details) => {
              if (details.reason === "input-change") setSearch(next);
            }}
            value={options.find((option) => option.value === value) ?? null}
            itemToStringLabel={(option) =>
              `${option.label} ${option.searchLabel ?? ""}`
            }
            itemToStringValue={(option) => option.value}
            onValueChange={(option) => {
              if (option) {
                onChange(option.value);
                setOpen(false);
                setSearch("");
              }
            }}
          >
            <div className="p-1">
              <ComboboxInput
                autoFocus={autoFocusSearch}
                showTrigger={false}
                placeholder={searchPlaceholder}
                aria-label={searchPlaceholder}
                onClick={(event) => event.stopPropagation()}
                onKeyDown={(event) => {
                  if (event.key !== "Escape") event.stopPropagation();
                }}
              />
            </div>
            <ComboboxList className="group/combobox-list max-h-72 border-border border-t">
              <ComboboxCollection>
                {(option: FilterOption<Value>) => (
                  <ComboboxItem
                    key={option.value}
                    value={option}
                    className="!ps-7.5"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {option.icon}
                    {option.label}
                  </ComboboxItem>
                )}
              </ComboboxCollection>
              <ComboboxEmpty className="group-data-empty/combobox-list:flex">
                No matches. Try another search.
              </ComboboxEmpty>
            </ComboboxList>
          </Combobox>
        </DropdownMenuSubContent>
      </DropdownMenuSub>
    );
  }

  return (
    <FilterSubMenu
      label={label}
      value={selected}
      active={value !== defaultValue}
    >
      <DropdownMenuRadioGroup
        value={value}
        onValueChange={(next) => onChange(next as Value)}
      >
        {options.map((option) => (
          <DropdownMenuRadioItem key={option.value} value={option.value}>
            {option.icon}
            {option.label}
          </DropdownMenuRadioItem>
        ))}
      </DropdownMenuRadioGroup>
    </FilterSubMenu>
  );
}

export function FilterCheckboxSubMenu<Value extends string>({
  label,
  summary,
  allLabel,
  options,
  selected,
  active,
  onToggle,
  onClear,
}: {
  label: string;
  summary: string;
  allLabel: string;
  options: readonly FilterOption<Value>[];
  selected: readonly Value[];
  /** For a filter whose default is a selection rather than an empty one. */
  active?: boolean;
  onToggle: (value: Value) => void;
  onClear: () => void;
}): ReactElement {
  return (
    <FilterSubMenu
      label={label}
      value={summary}
      active={active ?? selected.length > 0}
    >
      <DropdownMenuCheckboxItem
        checked={selected.length === 0}
        closeOnClick={false}
        onCheckedChange={onClear}
      >
        {allLabel}
      </DropdownMenuCheckboxItem>
      {options.map((option) => (
        <DropdownMenuCheckboxItem
          key={option.value}
          checked={selected.includes(option.value)}
          closeOnClick={false}
          onCheckedChange={() => onToggle(option.value)}
        >
          {option.icon}
          {option.label}
        </DropdownMenuCheckboxItem>
      ))}
    </FilterSubMenu>
  );
}

export function FilterClearItem({
  active,
  dataAttr,
  onClear,
}: {
  active: boolean;
  dataAttr: string;
  onClear: () => void;
}): ReactElement | null {
  if (!active) return null;

  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        data-attr={dataAttr}
        variant="destructive"
        onClick={onClear}
      >
        Clear filters
      </DropdownMenuItem>
    </>
  );
}
