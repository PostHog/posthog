import { Box, Dialog, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import {
  CATEGORY_LABELS,
  formatHotkeyParts,
  getShortcutsByCategory,
  type ShortcutCategory,
} from "../features/command/keyboard-shortcuts";

function Keycap({ label, size = "md" }: { label: string; size?: "sm" | "md" }) {
  const [pressed, setPressed] = useState(false);
  const isSmall = size === "sm";
  const minW = isSmall ? "22px" : "28px";
  const h = isSmall ? "22px" : "28px";
  const fontSize = isSmall ? "11px" : "13px";
  const shadowSize = isSmall ? "2px" : "3px";

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: cosmetic press animation
    <span
      role="presentation"
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => setPressed(false)}
      onMouseLeave={() => setPressed(false)}
      style={{
        minWidth: minW,
        height: h,
        fontSize,
        fontFamily: "system-ui, -apple-system, sans-serif",
        lineHeight: 1,
        borderBottomWidth: pressed ? "1px" : shadowSize,
        borderBottomColor: "var(--gray-7)",
        transform: pressed
          ? `translateY(${isSmall ? "1px" : "2px"})`
          : "translateY(0)",
        transition:
          "transform 80ms ease-out, border-bottom-width 80ms ease-out",
      }}
      className="box-border inline-flex cursor-pointer select-none items-center justify-center rounded-[6px] border border-(--gray-5) bg-(--gray-3) px-[6px] py-0 font-medium text-(--gray-11)"
    >
      {label}
    </span>
  );
}

interface KeyboardShortcutsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function KeyboardShortcutsSheet({
  open,
  onOpenChange,
}: KeyboardShortcutsSheetProps) {
  useHotkeys("escape", () => onOpenChange(false), {
    enabled: open,
    enableOnContentEditable: true,
    enableOnFormTags: true,
    preventDefault: true,
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content
        maxWidth="600px"
        onEscapeKeyDown={(e) => e.preventDefault()}
        className="max-h-[80vh] overflow-hidden"
      >
        <Flex align="start" justify="between" className="relative">
          <ShortcutsHeader />
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="shrink-0 cursor-pointer [all:unset]"
          >
            <Keycap label="Esc" size="sm" />
          </button>
        </Flex>

        <Box className="max-h-[calc(80vh-120px)] overflow-y-auto pr-[8px]">
          <KeyboardShortcutsList />
        </Box>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function ShortcutsHeader() {
  const triggerParts = formatHotkeyParts("mod+/");

  return (
    <Box mb="4">
      <Flex align="center" gap="3" mb="1">
        <Dialog.Title mb="0" className="text-2xl leading-[1.2]">
          Keyboard Combos
        </Dialog.Title>
        <Flex gap="1" align="center">
          {triggerParts.map((part) => (
            <Keycap key={part} label={part} />
          ))}
        </Flex>
      </Flex>
      <Text color="gray" className="text-sm">
        Your cheat codes for shipping faster
      </Text>
    </Box>
  );
}

export function KeyboardShortcutsList() {
  const shortcutsByCategory = useMemo(() => getShortcutsByCategory(), []);

  const categoryOrder: ShortcutCategory[] = [
    "general",
    "navigation",
    "panels",
    "editor",
  ];

  return (
    <Flex direction="column" gap="5">
      {categoryOrder.map((category) => {
        const shortcuts = shortcutsByCategory[category];
        if (shortcuts.length === 0) return null;

        const uniqueShortcuts = shortcuts.reduce(
          (acc, shortcut) => {
            const existing = acc.find(
              (s) => s.description === shortcut.description,
            );
            if (!existing) {
              acc.push(shortcut);
            }
            return acc;
          },
          [] as typeof shortcuts,
        );

        return (
          <Flex key={category} direction="column" gap="2">
            <Text color="gray" className="font-bold text-base">
              {CATEGORY_LABELS[category]}
            </Text>
            <Box className="overflow-hidden rounded-(--radius-2) border border-(--gray-5)">
              {uniqueShortcuts.map((shortcut) => (
                <Flex
                  key={shortcut.id}
                  align="center"
                  justify="between"
                  px="3"
                  className="border-b border-b-(--gray-4) pt-[6px] pb-[6px] last:border-b-0 odd:bg-(--gray-2) even:bg-(--gray-1)"
                >
                  <Text className="text-sm">{shortcut.description}</Text>
                  <ShortcutKeys
                    keys={shortcut.keys}
                    alternateKeys={shortcut.alternateKeys}
                  />
                </Flex>
              ))}
            </Box>
          </Flex>
        );
      })}
    </Flex>
  );
}

function SingleShortcutKeys({ keys }: { keys: string }) {
  const parts = formatHotkeyParts(keys);

  return (
    <Flex gap="1" align="center">
      {parts.map((part) => (
        <Keycap key={part} label={part} />
      ))}
    </Flex>
  );
}

function ShortcutKeys({
  keys,
  alternateKeys,
}: {
  keys: string;
  alternateKeys?: string;
}) {
  if (!alternateKeys) {
    return <SingleShortcutKeys keys={keys} />;
  }

  return (
    <Flex gap="1" align="center">
      <SingleShortcutKeys keys={keys} />
      <Text color="gray" className="text-[13px]">
        or
      </Text>
      <SingleShortcutKeys keys={alternateKeys} />
    </Flex>
  );
}
