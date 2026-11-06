import { cn } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import type { ComponentProps } from "react";

interface LoadingStateProps extends Omit<ComponentProps<"div">, "children"> {
  label?: string;
}

export function LoadingState({
  label,
  className,
  ...props
}: LoadingStateProps) {
  return (
    <div
      className={cn(
        "flex h-full w-full flex-col items-center justify-center gap-3 text-gray-9",
        className,
      )}
      {...props}
    >
      <Spinner size="lg" label={label} />
      {label && (
        <span aria-hidden="true" className="text-gray-11 text-sm">
          {label}
        </span>
      )}
    </div>
  );
}
