# typed: false
# frozen_string_literal: true

# This file is auto-updated by CI on semver releases. DO NOT EDIT.
class Phrocs < Formula
  desc "PostHog development process runner"
  homepage "https://github.com/PostHog/posthog/tree/master/tools/phrocs"
  version "VERSION_PLACEHOLDER"

  on_macos do
    on_intel do
      url "https://github.com/PostHog/posthog/releases/download/phrocs-VERSION_PLACEHOLDER/phrocs-darwin-amd64"
      sha256 "SHA256_DARWIN_AMD64"
    end
    on_arm do
      url "https://github.com/PostHog/posthog/releases/download/phrocs-VERSION_PLACEHOLDER/phrocs-darwin-arm64"
      sha256 "SHA256_DARWIN_ARM64"
    end
  end
  on_linux do
    on_intel do
      url "https://github.com/PostHog/posthog/releases/download/phrocs-VERSION_PLACEHOLDER/phrocs-linux-amd64"
      sha256 "SHA256_LINUX_AMD64"
    end
    on_arm do
      url "https://github.com/PostHog/posthog/releases/download/phrocs-VERSION_PLACEHOLDER/phrocs-linux-arm64"
      sha256 "SHA256_LINUX_ARM64"
    end
  end

  def install
    arch = Hardware::CPU.arm? ? "arm64" : "amd64"
    os = OS.mac? ? "darwin" : "linux"
    bin.install "phrocs-#{os}-#{arch}" => "phrocs"
  end

  test do
    assert_match "phrocs #{version}", shell_output("#{bin}/phrocs --version")
  end
end
