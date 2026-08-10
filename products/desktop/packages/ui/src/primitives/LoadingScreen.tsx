import { cn } from "@posthog/quill";
import { LoadingLogo } from "@posthog/ui/primitives/LoadingLogo";

interface LoadingScreenProps {
  logoSize?: number;
  className?: string;
}

export function LoadingScreen({
  logoSize = 96,
  className,
}: LoadingScreenProps) {
  return (
    <div
      className={cn(
        "flex h-full w-full items-center justify-center bg-(--color-background)",
        className,
      )}
    >
      <LoadingLogo size={logoSize} />
    </div>
  );
}
