import { Box } from "@radix-ui/themes";
import type React from "react";

interface BackgroundWrapperProps {
  children: React.ReactNode;
}

export const BackgroundWrapper: React.FC<BackgroundWrapperProps> = ({
  children,
}) => {
  return <Box height="100%">{children}</Box>;
};
