import {
  type Environment,
  slugifyEnvironmentName,
} from "@posthog/workspace-client/environment";
import { Button, Flex, Text } from "@radix-ui/themes";

interface EnvironmentRowProps {
  environment: Environment;
  isLast: boolean;
  onClick: () => void;
}

export function EnvironmentRow({
  environment,
  isLast,
  onClick,
}: EnvironmentRowProps) {
  const filename = `${slugifyEnvironmentName(environment.name)}.toml`;

  return (
    <Flex
      align="center"
      justify="between"
      gap="2"
      py="2"
      style={{
        borderBottom: isLast ? undefined : "1px solid var(--gray-4)",
      }}
    >
      <Flex direction="column" className="min-w-0">
        <Text truncate className="text-[13px]">
          {environment.name}
        </Text>
        <Text color="gray" truncate className="text-[12px]">
          {filename}
        </Text>
      </Flex>
      <Button
        variant="ghost"
        color="gray"
        size="1"
        onClick={onClick}
        className="shrink-0"
      >
        View
      </Button>
    </Flex>
  );
}
