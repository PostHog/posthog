import { EXTERNAL_LINKS } from "@posthog/shared";
import { UpdateBanner } from "@posthog/ui/features/sidebar/components/UpdateBanner";
import { FullScreenLayout as UiFullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import type { ReactNode } from "react";

interface FullScreenLayoutProps {
  children: ReactNode;
  footerLeft?: ReactNode;
  footerRight?: ReactNode;
}

export function FullScreenLayout(props: FullScreenLayoutProps) {
  return (
    <UiFullScreenLayout
      {...props}
      banner={<UpdateBanner variant="compact" />}
      onOpenSupport={() => openExternalUrl(EXTERNAL_LINKS.discord)}
    />
  );
}
