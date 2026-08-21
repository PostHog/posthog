import { Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

interface UsageCardProps {
  icon?: ReactNode;
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function UsageCard({ icon, title, actions, children }: UsageCardProps) {
  return (
    <Flex
      direction="column"
      gap="3"
      p="4"
      className="rounded-(--radius-3) border border-(--gray-5)"
    >
      <Flex align="center" gap="2">
        {icon}
        <Text className="font-medium text-sm">{title}</Text>
        <Flex flexGrow="1" />
        {actions}
      </Flex>
      {children}
    </Flex>
  );
}
