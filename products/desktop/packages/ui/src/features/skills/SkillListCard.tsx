import { Box, Flex, Text } from "@radix-ui/themes";
import type { ReactNode, Ref } from "react";

interface SkillListCardProps {
  /** Forwarded to the row element (e.g. for scroll-into-view). */
  cardRef?: Ref<HTMLDivElement>;
  icon: ReactNode;
  /** Tailwind classes for the icon chip; defaults to the neutral gray chip. */
  iconClass?: string;
  title: string;
  subtitle?: string;
  isSelected: boolean;
  /** Renders the row muted (e.g. a switched-off skill). */
  dimmed?: boolean;
  onClick: () => void;
  /** Badges or counts rendered after the text block. */
  trailing?: ReactNode;
}

/** Shared card row for every skills list (local, team, marketplace). */
export function SkillListCard({
  cardRef,
  icon,
  iconClass,
  title,
  subtitle,
  isSelected,
  dimmed,
  onClick,
  trailing,
}: SkillListCardProps) {
  return (
    <Flex
      ref={cardRef}
      align="center"
      gap="2"
      px="3"
      py="2"
      className={`cursor-pointer rounded-lg border transition-colors ${
        isSelected
          ? "border-accent-8 bg-accent-3"
          : "border-gray-6 bg-gray-2 hover:border-gray-8 hover:bg-gray-3"
      }`}
      onClick={onClick}
    >
      <Box
        className={`flex shrink-0 items-center justify-center rounded p-1.5 ${iconClass ?? "bg-gray-4 text-gray-11"} ${dimmed ? "opacity-40" : ""}`}
      >
        {icon}
      </Box>

      <Flex
        direction="column"
        gap="0"
        className={`min-w-0 flex-1 ${dimmed ? "opacity-40" : ""}`}
      >
        <Text className="truncate font-medium text-[13px] text-gray-12">
          {title}
        </Text>
        {subtitle && (
          <Text className="truncate text-[12px] text-gray-10">{subtitle}</Text>
        )}
      </Flex>

      {trailing}
    </Flex>
  );
}
