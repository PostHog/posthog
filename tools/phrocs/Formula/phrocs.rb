# typed: false
# frozen_string_literal: true

# This file is auto-updated by CI on semver releases. DO NOT EDIT.
class Phrocs < Formula
  desc "PostHog development process runner"
  homepage "https://github.com/PostHog/posthog/tree/master/tools/phrocs"
  version "VERSION_PLACEHOLDER"

  if OS.mac?
    if Hardware::CPU.intel?
      url "https://github.com/PostHog/posthog/releases/download/phrocs/VERSION_PLACEHOLDER/phrocs-darwin-amd64"
      sha256 "SHA256_DARWIN_AMD64"

      define_method(:install) do
        bin.install "phrocs-darwin-amd64" => "phrocs"
      end
    end
    if Hardware::CPU.arm?
      url "https://github.com/PostHog/posthog/releases/download/phrocs/VERSION_PLACEHOLDER/phrocs-darwin-arm64"
      sha256 "SHA256_DARWIN_ARM64"

      define_method(:install) do
        bin.install "phrocs-darwin-arm64" => "phrocs"
      end
    end
  end
  if OS.linux?
    if Hardware::CPU.intel?
      url "https://github.com/PostHog/posthog/releases/download/phrocs/VERSION_PLACEHOLDER/phrocs-linux-amd64"
      sha256 "SHA256_LINUX_AMD64"

      define_method(:install) do
        bin.install "phrocs-linux-amd64" => "phrocs"
      end
    end
    if Hardware::CPU.arm?
      url "https://github.com/PostHog/posthog/releases/download/phrocs/VERSION_PLACEHOLDER/phrocs-linux-arm64"
      sha256 "SHA256_LINUX_ARM64"

      define_method(:install) do
        bin.install "phrocs-linux-arm64" => "phrocs"
      end
    end
  end

  test do
    assert_match "phrocs #{version}", shell_output("#{bin}/phrocs --version")
  end
end
