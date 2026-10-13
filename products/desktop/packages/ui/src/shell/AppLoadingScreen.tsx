import { Skeleton } from "@posthog/quill";
import { EXTERNAL_LINKS } from "@posthog/shared";
import { Button } from "@posthog/ui/primitives/Button";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useEffect, useState } from "react";

// The gate spans bootstrap (20s deadline in core auth), the access check and
// the initial route load, so this sits well above all three combined before
// declaring boot stuck.
const STALL_TIMEOUT_MS = 30_000;

function AppBootShell(): React.ReactNode {
  return (
    <output
      aria-label="PostHog is starting"
      className="flex min-h-screen w-full bg-(--color-background)"
      data-testid="app-loading-shell"
    >
      <aside className="flex w-64 shrink-0 flex-col border-(--gray-5) border-r bg-(--gray-2) px-3 pt-12 pb-3">
        <Skeleton className="mb-5 h-7 w-28" />
        <div className="flex flex-col gap-2">
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-7 w-[88%]" />
          <Skeleton className="h-7 w-[72%]" />
        </div>
        <div className="mt-7 flex flex-col gap-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-7 w-[92%]" />
          <Skeleton className="h-7 w-[84%]" />
          <Skeleton className="h-7 w-[96%]" />
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center border-(--gray-5) border-b px-4">
          <Skeleton className="h-6 w-36" />
        </div>
        <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-5 px-8 py-10">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-[62%]" />
          <div className="mt-3 flex flex-col gap-3">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        </div>
      </main>
    </output>
  );
}

export function AppLoadingScreen(): React.ReactNode {
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setStalled(true), STALL_TIMEOUT_MS);
    return () => clearTimeout(id);
  }, []);

  if (!stalled) {
    return <AppBootShell />;
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex max-w-[360px] flex-col items-center gap-4 text-center">
        <p className="font-bold text-lg">
          PostHog is taking longer than expected to start
        </p>
        <p className="text-(--gray-11)">
          This usually clears up with a restart.
        </p>
        <div className="flex gap-3">
          <Button onClick={() => window.location.reload()}>Retry</Button>
          <Button
            variant="soft"
            onClick={() => openExternalUrl(EXTERNAL_LINKS.discord)}
          >
            Get support
          </Button>
        </div>
      </div>
    </div>
  );
}
