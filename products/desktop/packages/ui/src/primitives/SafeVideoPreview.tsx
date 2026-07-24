import {
  buildVideoDataUrl,
  isAllowedVideoMimeType,
  MAX_VIDEO_BASE64_LENGTH,
} from "@posthog/shared";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";

interface SafeVideoPreviewProps {
  /** Base64-encoded video data (no data URL prefix). */
  base64: string;
  mimeType: string;
  /** Accessible label for the player. */
  label?: string;
  className?: string;
  style?: React.CSSProperties;
  /** Rendered when the video fails to decode or has a disallowed mime type. */
  fallback?: React.ReactNode;
}

function DefaultFallback() {
  return (
    <Flex
      align="center"
      justify="center"
      className="size-full min-h-12 p-3 text-(--gray-11)"
    >
      <Text className="text-[13px]">Unable to render video preview</Text>
    </Flex>
  );
}

export function SafeVideoPreview({
  base64,
  mimeType,
  label,
  className,
  style,
  fallback,
}: SafeVideoPreviewProps) {
  const [hasError, setHasError] = useState(false);
  const [lastSource, setLastSource] = useState({ base64, mimeType });

  if (lastSource.base64 !== base64 || lastSource.mimeType !== mimeType) {
    setLastSource({ base64, mimeType });
    setHasError(false);
  }

  const isPayloadValid =
    base64.length > 0 &&
    base64.length <= MAX_VIDEO_BASE64_LENGTH &&
    isAllowedVideoMimeType(mimeType);

  if (!isPayloadValid || hasError) {
    return <>{fallback ?? <DefaultFallback />}</>;
  }

  return (
    // muted by default so scrolling a diff never blasts audio; the user can
    // unmute via the native controls. (muted also satisfies useMediaCaption.)
    <video
      controls
      muted
      preload="metadata"
      aria-label={label ?? "video preview"}
      src={buildVideoDataUrl(mimeType, base64)}
      className={className ?? "max-h-full max-w-full"}
      style={style}
      onError={() => setHasError(true)}
    />
  );
}
