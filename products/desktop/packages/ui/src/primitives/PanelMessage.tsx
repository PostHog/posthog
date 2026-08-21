import { Box, Flex, Text } from "@radix-ui/themes";

interface PanelMessageProps {
  children: React.ReactNode;
  detail?: string;
  color?: "gray" | "red";
}

export function PanelMessage({
  children,
  detail,
  color = "gray",
}: PanelMessageProps) {
  return (
    <Box height="100%" p="4">
      <Flex
        align="center"
        justify="center"
        direction="column"
        gap="1"
        height="100%"
      >
        <Text color={color} className="text-sm">
          {children}
        </Text>
        {detail && (
          <Text color="gray" trim="both" className="text-[13px]">
            {detail}
          </Text>
        )}
      </Flex>
    </Box>
  );
}
