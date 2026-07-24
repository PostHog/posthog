import {
  buildImageDataUrl,
  isAllowedImageMimeType,
  MAX_IMAGE_BASE64_LENGTH,
} from "@posthog/shared";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useImagePanAndZoom } from "./hooks/useImagePanAndZoom";

interface SafeImagePreviewProps {
  /** Base64-encoded image data (no data URL prefix). */
  base64: string;
  mimeType: string;
  alt?: string;
  className?: string;
  style?: React.CSSProperties;
  /** Rendered when the image fails to decode or has a disallowed mime type. */
  fallback?: React.ReactNode;
}

function DefaultFallback() {
  return (
    <Flex
      align="center"
      justify="center"
      className="size-full min-h-12 p-3 text-(--gray-11)"
    >
      <Text className="text-[13px]">Unable to render image preview</Text>
    </Flex>
  );
}

export function SafeImagePreview({
  base64,
  mimeType,
  alt,
  className,
  style,
  fallback,
}: SafeImagePreviewProps) {
  const [hasError, setHasError] = useState(false);
  const [lastSource, setLastSource] = useState({ base64, mimeType });
  const zoom = useImagePanAndZoom();

  if (lastSource.base64 !== base64 || lastSource.mimeType !== mimeType) {
    setLastSource({ base64, mimeType });
    setHasError(false);
  }

  const isPayloadValid =
    base64.length > 0 &&
    base64.length <= MAX_IMAGE_BASE64_LENGTH &&
    isAllowedImageMimeType(mimeType);

  if (!isPayloadValid || hasError) {
    return <>{fallback ?? <DefaultFallback />}</>;
  }

  return (
    <div
      ref={zoom.containerRef}
      className={`flex touch-none select-none items-center justify-center overflow-hidden ${className ?? "max-h-full max-w-full"}`}
      style={{
        ...style,
        cursor: zoom.isDragging
          ? "grabbing"
          : zoom.isZoomed
            ? "grab"
            : style?.cursor,
      }}
    >
      <img
        src={buildImageDataUrl(mimeType, base64)}
        alt={alt ?? "image preview"}
        draggable={false}
        className="max-h-full max-w-full object-contain"
        style={{
          transform: zoom.transform,
          transformOrigin: "center center",
          willChange: "transform",
        }}
        onError={() => setHasError(true)}
      />
    </div>
  );
}
