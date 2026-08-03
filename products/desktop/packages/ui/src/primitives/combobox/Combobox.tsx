import { Check, MagnifyingGlass } from "@phosphor-icons/react";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { Button, Flex, Popover } from "@radix-ui/themes";
import type { Responsive } from "@radix-ui/themes/dist/esm/props/prop-def.js";
import { Command as CmdkCommand } from "cmdk";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Tooltip } from "../Tooltip";
import "./Combobox.css";
import {
  type ComboboxSearchKeys,
  useComboboxFilter,
} from "./useComboboxFilter";

type ComboboxSize = "1" | "2" | "3";
type ComboboxContentVariant = "solid" | "soft";

interface ComboboxContextValue {
  size: ComboboxSize;
  value: string;
  onValueChange: (value: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled: boolean;
  registerItem: (value: string, label: string) => void;
  unregisterItem: (value: string) => void;
  getItemLabel: (value: string) => string | undefined;
}

const ComboboxContext = createContext<ComboboxContextValue | null>(null);

function useComboboxContext() {
  const context = useContext(ComboboxContext);
  if (!context) {
    throw new Error("Combobox components must be used within Combobox.Root");
  }
  return context;
}

interface FilterContextValue {
  onSearchChange: (value: string) => void;
}

const FilterContext = createContext<FilterContextValue | null>(null);

interface ComboboxRootProps {
  children: React.ReactNode;
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  size?: ComboboxSize;
  disabled?: boolean;
}

function ComboboxRoot({
  children,
  value: controlledValue,
  defaultValue = "",
  onValueChange,
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  size = "2",
  disabled = false,
}: ComboboxRootProps) {
  const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue);
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const itemLabelsRef = useRef<Map<string, string>>(new Map());

  const value = controlledValue ?? uncontrolledValue;
  const open = controlledOpen ?? uncontrolledOpen;

  const handleValueChange = useCallback(
    (newValue: string) => {
      if (controlledValue === undefined) {
        setUncontrolledValue(newValue);
      }
      onValueChange?.(newValue);
    },
    [controlledValue, onValueChange],
  );

  const handleOpenChange = useCallback(
    (newOpen: boolean) => {
      if (controlledOpen === undefined) {
        setUncontrolledOpen(newOpen);
      }
      onOpenChange?.(newOpen);
    },
    [controlledOpen, onOpenChange],
  );

  const registerItem = useCallback((itemValue: string, label: string) => {
    itemLabelsRef.current.set(itemValue, label);
  }, []);

  const unregisterItem = useCallback((itemValue: string) => {
    itemLabelsRef.current.delete(itemValue);
  }, []);

  const getItemLabel = useCallback((itemValue: string) => {
    return itemLabelsRef.current.get(itemValue);
  }, []);

  const contextValue = useMemo<ComboboxContextValue>(
    () => ({
      size,
      value,
      onValueChange: handleValueChange,
      open,
      onOpenChange: handleOpenChange,
      disabled,
      registerItem,
      unregisterItem,
      getItemLabel,
    }),
    [
      size,
      value,
      handleValueChange,
      open,
      handleOpenChange,
      disabled,
      registerItem,
      unregisterItem,
      getItemLabel,
    ],
  );

  return (
    <ComboboxContext.Provider value={contextValue}>
      <Popover.Root open={open} onOpenChange={handleOpenChange}>
        {children}
      </Popover.Root>
    </ComboboxContext.Provider>
  );
}

interface ComboboxTriggerProps {
  children?: React.ReactNode;
  className?: string;
  variant?: "outline" | "ghost" | "surface" | "soft" | "classic";
  color?: string;
  placeholder?: string;
  style?: React.CSSProperties;
}

function ComboboxTrigger({
  children,
  className = "",
  variant = "outline",
  placeholder = "Select...",
  style,
}: ComboboxTriggerProps) {
  const { size, value, open, disabled, getItemLabel } = useComboboxContext();

  const displayValue =
    children ?? (getItemLabel(value) || value || placeholder);

  return (
    <Popover.Trigger>
      <Button
        color="gray"
        variant={variant}
        size={size as Responsive<"1" | "2" | "3">}
        disabled={disabled}
        className={className}
        data-state={open ? "open" : "closed"}
        style={style}
      >
        <Flex justify="between" align="center" gap="2">
          <Flex align="center" gap="2" className="min-w-0">
            {displayValue}
          </Flex>
          {!disabled && <ChevronDownIcon className="shrink-0" />}
        </Flex>
      </Button>
    </Popover.Trigger>
  );
}

interface FilterResult<T> {
  filtered: T[];
  hasMore: boolean;
  moreCount: number;
}

interface ComboboxContentBaseProps {
  className?: string;
  variant?: ComboboxContentVariant;
  side?: "top" | "right" | "bottom" | "left";
  sideOffset?: number;
  align?: "start" | "center" | "end";
  style?: React.CSSProperties;
}

interface ComboboxContentStaticProps extends ComboboxContentBaseProps {
  items?: undefined;
  shouldFilter?: boolean;
  children: React.ReactNode;
}

interface ComboboxContentFilteredProps<T> extends ComboboxContentBaseProps {
  /** Items to filter. Activates built-in fuzzy filtering (bypasses cmdk). */
  items: T[];
  /** Extract the searchable string from each item. Defaults to `String(item)`. */
  getValue?: (item: T) => string;
  /**
   * Opt-in weighted fuzzy search across multiple fields (fuse.js). Each key
   * carries a weight (e.g. name above description) and prefix matches on
   * `getValue` are promoted. Pass a stable reference (a module constant).
   */
  searchKeys?: ComboboxSearchKeys<T>;
  /** Maximum items to render. Defaults to 50. */
  limit?: number;
  /** Values pinned to the top regardless of score. */
  pinned?: string[];
  children: (result: FilterResult<T>) => React.ReactNode;
}

type ComboboxContentProps<T = never> =
  | ComboboxContentStaticProps
  | ComboboxContentFilteredProps<T>;

function ComboboxContent<T>({
  children,
  className = "",
  variant = "soft",
  side = "bottom",
  sideOffset = 4,
  align = "start",
  style,
  ...rest
}: ComboboxContentProps<T>) {
  const { size, open, onOpenChange } = useComboboxContext();

  const hasItems = "items" in rest && rest.items !== undefined;
  const filterItems = hasItems ? rest.items : ([] as T[]);
  const getValue = hasItems ? rest.getValue : undefined;
  const searchKeys = hasItems ? rest.searchKeys : undefined;
  const limit = hasItems ? rest.limit : undefined;
  const pinned = hasItems ? rest.pinned : undefined;
  const shouldFilter = hasItems
    ? false
    : "shouldFilter" in rest
      ? (rest.shouldFilter ?? true)
      : true;

  const filter = useComboboxFilter(
    filterItems,
    { limit, pinned, open, keys: searchKeys },
    getValue,
  );

  const resolvedChildren = hasItems
    ? (children as (result: FilterResult<T>) => React.ReactNode)(filter)
    : (children as React.ReactNode);

  const hasInput = React.Children.toArray(resolvedChildren).some(
    (child) => React.isValidElement(child) && child.type === ComboboxInput,
  );

  const content = (
    <Popover.Content
      className={`combobox-content p-0 size-${size} variant-${variant} ${className}`}
      side={side}
      sideOffset={sideOffset}
      align={align}
      style={{
        minWidth: "min(var(--radix-popover-trigger-width), 300px)",
        ...style,
      }}
      onInteractOutside={(e) => {
        const target = e.target as HTMLElement;
        if (target.closest(".combobox-trigger")) {
          e.preventDefault();
          return;
        }
        onOpenChange(false);
      }}
      onEscapeKeyDown={() => onOpenChange(false)}
    >
      <CmdkCommand shouldFilter={shouldFilter} loop>
        {hasInput &&
          React.Children.map(resolvedChildren, (child) =>
            React.isValidElement(child) && child.type === ComboboxInput
              ? child
              : null,
          )}
        <CmdkCommand.List>
          {React.Children.map(resolvedChildren, (child) =>
            React.isValidElement(child) &&
            child.type !== ComboboxInput &&
            child.type !== ComboboxFooter
              ? child
              : null,
          )}
        </CmdkCommand.List>
        {React.Children.map(resolvedChildren, (child) =>
          React.isValidElement(child) && child.type === ComboboxFooter
            ? child
            : null,
        )}
      </CmdkCommand>
    </Popover.Content>
  );

  if (hasItems) {
    return (
      <FilterContext.Provider value={{ onSearchChange: filter.onSearchChange }}>
        {content}
      </FilterContext.Provider>
    );
  }

  return content;
}

interface ComboboxInputProps {
  placeholder?: string;
  className?: string;
  value?: string;
  onValueChange?: (value: string) => void;
}

const ComboboxInput = React.forwardRef<
  React.ElementRef<typeof CmdkCommand.Input>,
  ComboboxInputProps
>(({ placeholder = "Search...", className, value, onValueChange }, ref) => {
  const filterCtx = useContext(FilterContext);
  const handleValueChange = onValueChange ?? filterCtx?.onSearchChange;

  return (
    <div className="combobox-input-wrapper">
      <MagnifyingGlass
        size={12}
        weight="regular"
        className="combobox-input-icon"
      />
      <CmdkCommand.Input
        ref={ref}
        className={className}
        placeholder={placeholder}
        value={value}
        onValueChange={handleValueChange}
        autoFocus
      />
    </div>
  );
});

ComboboxInput.displayName = "ComboboxInput";

interface ComboboxItemProps {
  children: React.ReactNode;
  value: string;
  disabled?: boolean;
  className?: string;
  textValue?: string;
  icon?: React.ReactNode;
  /** Optional muted second line, truncated to one line. */
  description?: React.ReactNode;
}

const ComboboxItem = React.forwardRef<
  React.ElementRef<typeof CmdkCommand.Item>,
  ComboboxItemProps
>(
  (
    { children, value, disabled, className, textValue, icon, description },
    ref,
  ) => {
    const {
      value: selectedValue,
      onValueChange,
      onOpenChange,
      registerItem,
      unregisterItem,
    } = useComboboxContext();

    const textRef = useRef<HTMLSpanElement>(null);
    const itemRef = useRef<HTMLDivElement>(null);
    const [showTooltip, setShowTooltip] = useState(false);

    useEffect(() => {
      const label =
        textValue || (typeof children === "string" ? children : value);
      registerItem(value, label);
      return () => unregisterItem(value);
    }, [value, children, textValue, registerItem, unregisterItem]);

    useEffect(() => {
      if (!showTooltip) return;
      const scrollParent = itemRef.current?.closest("[cmdk-list]");
      if (!scrollParent) return;
      const dismiss = () => setShowTooltip(false);
      scrollParent.addEventListener("scroll", dismiss, { passive: true });
      return () => scrollParent.removeEventListener("scroll", dismiss);
    }, [showTooltip]);

    const isSelected = selectedValue === value;

    const handleSelect = useCallback(() => {
      if (!disabled) {
        onValueChange(value);
        onOpenChange(false);
      }
    }, [disabled, value, onValueChange, onOpenChange]);

    const handleMouseEnter = useCallback(() => {
      const el = textRef.current;
      if (el && el.scrollWidth > el.clientWidth) {
        setShowTooltip(true);
      }
    }, []);

    const handleMouseLeave = useCallback(() => {
      setShowTooltip(false);
    }, []);

    const tooltipContent =
      textValue || (typeof children === "string" ? children : value);

    return (
      <Tooltip content={tooltipContent} open={showTooltip} side="top">
        <CmdkCommand.Item
          ref={(node) => {
            itemRef.current = node;
            if (typeof ref === "function") ref(node);
            else if (ref) ref.current = node;
          }}
          value={value}
          disabled={disabled}
          onSelect={handleSelect}
          className={className}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          <span className="combobox-item-content">
            {icon && <span className="combobox-item-icon">{icon}</span>}
            {description ? (
              <span className="combobox-item-text-group">
                <span ref={textRef} className="combobox-item-text">
                  {children}
                </span>
                <span className="combobox-item-description">{description}</span>
              </span>
            ) : (
              <span ref={textRef} className="combobox-item-text">
                {children}
              </span>
            )}
          </span>
          <span className="combobox-item-indicator">
            {isSelected && <Check weight="bold" size={14} />}
          </span>
        </CmdkCommand.Item>
      </Tooltip>
    );
  },
);

ComboboxItem.displayName = "ComboboxItem";

interface ComboboxGroupProps {
  children: React.ReactNode;
  heading?: string;
  className?: string;
}

const ComboboxGroup = React.forwardRef<
  React.ElementRef<typeof CmdkCommand.Group>,
  ComboboxGroupProps
>(({ children, heading, className }, ref) => {
  return (
    <CmdkCommand.Group ref={ref} heading={heading} className={className}>
      {children}
    </CmdkCommand.Group>
  );
});

ComboboxGroup.displayName = "ComboboxGroup";

interface ComboboxLabelProps {
  children: React.ReactNode;
  className?: string;
}

function ComboboxLabel({ children, className = "" }: ComboboxLabelProps) {
  return <div className={`combobox-label ${className}`}>{children}</div>;
}

interface ComboboxSeparatorProps {
  className?: string;
}

function ComboboxSeparator({ className = "" }: ComboboxSeparatorProps) {
  return (
    <CmdkCommand.Separator className={`combobox-separator ${className}`} />
  );
}

interface ComboboxEmptyProps {
  children?: React.ReactNode;
  className?: string;
}

const ComboboxEmpty = React.forwardRef<
  React.ElementRef<typeof CmdkCommand.Empty>,
  ComboboxEmptyProps
>(({ children = "No results found.", className }, ref) => {
  return (
    <CmdkCommand.Empty ref={ref} className={className}>
      {children}
    </CmdkCommand.Empty>
  );
});

ComboboxEmpty.displayName = "ComboboxEmpty";

interface ComboboxFooterProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

function ComboboxFooter({
  children,
  className = "",
  style,
}: ComboboxFooterProps) {
  return (
    <div className={`combobox-footer ${className}`} style={style}>
      {children}
    </div>
  );
}

export const Combobox = {
  Root: ComboboxRoot,
  Trigger: ComboboxTrigger,
  Content: ComboboxContent,
  Input: ComboboxInput,
  Item: ComboboxItem,
  Group: ComboboxGroup,
  Label: ComboboxLabel,
  Separator: ComboboxSeparator,
  Empty: ComboboxEmpty,
  Footer: ComboboxFooter,
};
