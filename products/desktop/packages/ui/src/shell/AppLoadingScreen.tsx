import { EXTERNAL_LINKS } from "@posthog/shared";
import { Button } from "@posthog/ui/primitives/Button";
import { LoadingScreen } from "@posthog/ui/primitives/LoadingScreen";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Flex, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";

// The gate spans bootstrap (20s deadline in core auth), the access check and
// the initial route load, so this sits well above all three combined before
// declaring boot stuck.
const STALL_TIMEOUT_MS = 30_000;

export function AppLoadingScreen(): React.ReactNode {
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setStalled(true), STALL_TIMEOUT_MS);
    return () => clearTimeout(id);
  }, []);

  if (!stalled) {
    return <LoadingScreen className="min-h-screen" />;
  }

  return (
    <Flex align="center" justify="center" minHeight="100vh">
      <Flex
        direction="column"
        align="center"
        gap="4"
        className="max-w-[360px] text-center"
      >
        <Text size="4" weight="bold">
          PostHog is taking longer than expected to start
        </Text>
        <Text color="gray">This usually clears up with a restart.</Text>
        <Flex gap="3">
          <Button onClick={() => window.location.reload()}>Retry</Button>
          <Button
            variant="soft"
            onClick={() => openExternalUrl(EXTERNAL_LINKS.discord)}
          >
            Get support
          </Button>
        </Flex>
      </Flex>
    </Flex>
  );
}
