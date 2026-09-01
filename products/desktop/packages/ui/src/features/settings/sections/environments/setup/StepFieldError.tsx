import { Text } from "@posthog/quill";
import type { ReactNode } from "react";

export function StepFieldError({
  id,
  children,
}: {
  id?: string;
  children: ReactNode;
}) {
  return (
    <Text id={id} role="alert" className="text-(--red-11) text-[11.5px]">
      {children}
    </Text>
  );
}
