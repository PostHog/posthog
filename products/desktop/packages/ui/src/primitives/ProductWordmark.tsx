import { Text } from "@posthog/quill";
import Logo from "@posthog/ui/primitives/Logo";

/**
 * The hedgehog mark beside the product name. Logo's own wordmark is brand
 * lettering inside the SVG, so setting only part of the name as text cannot
 * match it. The whole name is text instead.
 */
export function ProductWordmark() {
  return (
    <div className="flex items-center gap-2">
      <span className="flex [&>svg]:h-[26px] [&>svg]:w-auto">
        <Logo wordmark={false} />
      </span>
      <Text className="font-bold text-(--gray-12) text-[25px] leading-none tracking-[-0.05em]">
        PostHog Desktop
      </Text>
    </div>
  );
}
