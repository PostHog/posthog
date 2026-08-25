import { Dot } from "@posthog/quill";

interface SidebarNotificationDotProps {
  show: boolean;
  title: string;
}

export function SidebarNotificationDot({
  show,
  title,
}: SidebarNotificationDotProps) {
  if (!show) return null;
  return <Dot variant="warning" className="ml-2" title={title} />;
}
