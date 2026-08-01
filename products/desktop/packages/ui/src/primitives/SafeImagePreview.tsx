import {
  ArrowsInSimple,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
} from "@phosphor-icons/react";
import {
  buildImageDataUrl,
  isAllowedImageMimeType,
  MAX_IMAGE_BASE64_LENGTH,
} from "@posthog/shared";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";

const MIN_SCALE = 0.1;
const MAX_SCALE = 8;
const SCALE_STEP = 0.25;

interface SafeImagePreviewProps {
  /** Base64-encoded image data (no data URL prefix). */
  base64: string;
  mimeType: string;
  alt?: string;
  className?: string;
  style?: React.CSSProperties;
  /** Rendered when the image fails to decode or has a disallowed mime type. */
  fallback?: React.ReactNode;
  controls?: boolean;
}

interface ZoomableImageProps {
  src: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
  controls?: boolean;
  onError?: () => void;
}

export function ZoomableImage({
  src,
  alt,
  className,
  style,
  controls = false,
  onError,
}: ZoomableImageProps) {
  const [scale, setScale] = useState(1);

  return (
    <div
      className={`relative overflow-hidden ${className ?? "max-h-full max-w-full"}`}
      style={style}
    >
      <TransformWrapper
        minScale={MIN_SCALE}
        maxScale={MAX_SCALE}
        centerOnInit
        centerZoomedOut
        smooth={false}
        wheel={{ wheelDisabled: true }}
        trackPadPanning={{ disabled: false }}
        doubleClick={{ mode: "reset" }}
        zoomAnimation={{ disabled: true }}
        onTransform={(_, state) => setScale(state.scale)}
      >
        {({ zoomIn, zoomOut, resetTransform }) => (
          <>
            <TransformComponent
              wrapperStyle={{ width: "100%", height: "100%" }}
              contentStyle={{
                width: "100%",
                height: "100%",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <img
                src={src}
                alt={alt}
                draggable={false}
                className="max-h-full max-w-full object-contain"
                onError={onError}
              />
            </TransformComponent>
            {controls && (
              <div className="-translate-x-1/2 absolute bottom-3 left-1/2 flex items-center gap-1 rounded-md border border-(--gray-a5) bg-(--color-panel-solid) p-1 shadow-sm">
                <button
                  type="button"
                  title="Zoom out"
                  aria-label="Zoom out"
                  disabled={scale <= MIN_SCALE}
                  onClick={() => zoomOut(SCALE_STEP, 0)}
                  className="flex size-7 items-center justify-center rounded text-(--gray-11) hover:bg-(--gray-a3) disabled:opacity-40"
                >
                  <MagnifyingGlassMinus size={16} />
                </button>
                <span className="w-11 text-center text-(--gray-11) text-xs">
                  {Math.round(scale * 100)}%
                </span>
                <button
                  type="button"
                  title="Zoom in"
                  aria-label="Zoom in"
                  disabled={scale >= MAX_SCALE}
                  onClick={() => zoomIn(SCALE_STEP, 0)}
                  className="flex size-7 items-center justify-center rounded text-(--gray-11) hover:bg-(--gray-a3) disabled:opacity-40"
                >
                  <MagnifyingGlassPlus size={16} />
                </button>
                <button
                  type="button"
                  title="Fit to view"
                  aria-label="Fit to view"
                  onClick={() => resetTransform(0)}
                  className="flex size-7 items-center justify-center rounded text-(--gray-11) hover:bg-(--gray-a3)"
                >
                  <ArrowsInSimple size={16} />
                </button>
              </div>
            )}
          </>
        )}
      </TransformWrapper>
    </div>
  );
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
  controls,
}: SafeImagePreviewProps) {
  const [hasError, setHasError] = useState(false);
  const [lastSource, setLastSource] = useState({ base64, mimeType });

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
    <ZoomableImage
      src={buildImageDataUrl(mimeType, base64)}
      alt={alt ?? "image preview"}
      className={className}
      style={style}
      controls={controls}
      onError={() => setHasError(true)}
    />
  );
}
