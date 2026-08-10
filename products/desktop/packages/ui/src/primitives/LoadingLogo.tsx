import { cn } from "@posthog/quill";

// The animated GIF this replaced drew the mark inset in a square canvas, so the mark
// covered 72% of the requested size. Keep that ratio so the loading screen looks the
// same, and derive the height from the 52x28 viewBox.
const MARK_WIDTH_RATIO = 0.72;
const MARK_ASPECT_RATIO = 52 / 28;

interface LoadingLogoProps {
  /** Box the logo used to be drawn into, in pixels. */
  size?: number;
  className?: string;
}

export function LoadingLogo({ size = 96, className }: LoadingLogoProps) {
  const width = size * MARK_WIDTH_RATIO;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 52 28"
      width={width}
      height={width / MARK_ASPECT_RATIO}
      aria-hidden="true"
      data-testid="app-loading-logo"
      className={cn(
        "pointer-events-none select-none fill-[#111] dark:fill-[#FAFAFA]",
        className,
      )}
    >
      <path d="M.87 19.13a.5.5 0 0 0-.87.34v5.94a2.6 2.6 0 0 0 2.59 2.58H7.8a.5.5 0 0 0 .37-.84zM.86 8.4c-.3-.32-.86-.1-.86.36v6.73q0 .2.13.34l8.81 9.68 1.8 2.06v-8.82zM4.59.82A2.67 2.67 0 0 0 0 2.68v1.93q0 .4.27.69l10.47 10.95v-9.1z" />
      <path d="M11.36 28h7.08a.5.5 0 0 0 .36-.85l-8.05-8.4v8.8l.23.28q.16.17.38.17m-.61-11.76 8.84 9.25 2.1 2.33q.1.11.27.14V18.7L10.75 7.15zm0-13.7v1.41a2 2 0 0 0 .55 1.28L21.96 16.2V7.65L15.32.8a2.67 2.67 0 0 0-4.57 1.71z" />
      <path d="M22.06 28h7.76a.5.5 0 0 0 .36-.86l-8.22-8.45v9.27l.09.02zM31 25.49l1.13 1.14c.32.31.85.09.85-.35v-7.3l-.49-.51L21.96 7.64v8.55zM22.52 5.73l9.62 9.89c.3.32.86.1.86-.35V7.46L26.56.82a2.67 2.67 0 0 0-4.59 1.84v1.7c0 .51.2 1 .57 1.37z" />
      <path d="m50 23.34-.35-.05A4.5 4.5 0 0 1 47 21.97L35.56 10.1c-.3-.33-.86-.1-.86.35V27.5c0 .27.22.5.5.5h13.78c1.48 0 2.67-1.2 2.67-2.67v-.1a1.9 1.9 0 0 0-1.67-1.89zm-10.81.2a1.8 1.8 0 1 1 0-3.58 1.8 1.8 0 0 1 0 3.58" />
    </svg>
  );
}
