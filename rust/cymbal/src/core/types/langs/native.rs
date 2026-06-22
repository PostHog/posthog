use serde::{Deserialize, Serialize};

use crate::error::NativeError;

/// A loaded module (binary image) reported by an SDK alongside native stack
/// frames, used to map absolute instruction addresses onto an uploaded debug
/// symbol set. Sent as the event-level `$debug_images` property.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DebugImage {
    pub debug_id: String,
    pub image_addr: String,
    #[serde(default)]
    pub image_vmaddr: Option<String>,
    #[serde(default)]
    pub image_size: Option<u64>,
    #[serde(default)]
    pub code_file: Option<String>,
    #[serde(default, rename = "type")]
    pub image_type: Option<String>,
    #[serde(default)]
    pub arch: Option<String>,
}

pub fn parse_hex_address(s: &str) -> Result<u64, NativeError> {
    let s = s.trim().trim_start_matches("0x").trim_start_matches("0X");
    u64::from_str_radix(s, 16).map_err(|_| NativeError::InvalidAddress(s.to_string()))
}

/// Find the debug image containing `instruction_addr`, preferring an exact
/// match on the frame's own `image_addr` and falling back to a range check
/// against each image's `[image_addr, image_addr + image_size)`.
pub fn find_debug_image<'a>(
    instruction_addr: u64,
    frame_image_addr: Option<&str>,
    debug_images: &'a [DebugImage],
) -> Result<&'a DebugImage, NativeError> {
    let frame_image_addr = frame_image_addr.and_then(|addr| parse_hex_address(addr).ok());

    for image in debug_images {
        let image_base = parse_hex_address(&image.image_addr).ok();

        if let (Some(frame_addr), Some(base)) = (frame_image_addr, image_base) {
            if frame_addr == base {
                return Ok(image);
            }
        }

        if let (Some(base), Some(size)) = (image_base, image.image_size) {
            if instruction_addr >= base && instruction_addr < base.saturating_add(size) {
                return Ok(image);
            }
        }
    }

    Err(NativeError::NoMatchingDebugImage)
}

/// Offset of `instruction_addr` from the image's runtime load address. The
/// symcache contains addresses relative to the binary's VM base, so the load
/// offset is all that's needed for lookup.
pub fn calculate_relative_addr(
    instruction_addr: u64,
    debug_image: &DebugImage,
) -> Result<u64, NativeError> {
    let image_addr = parse_hex_address(&debug_image.image_addr)?;

    if instruction_addr < image_addr {
        return Err(NativeError::InvalidAddress(format!(
            "instruction_addr 0x{:x} < image_addr 0x{:x}",
            instruction_addr, image_addr
        )));
    }

    Ok(instruction_addr - image_addr)
}

/// The launch-invariant identity of a frame: the debug image it belongs to and
/// the offset within it. Absolute instruction addresses are ASLR-slid per
/// process launch, so anything that needs a stable per-build frame identity
/// (e.g. frame-record caching) should prefer this over the raw address.
pub fn launch_invariant_addr(
    instruction_addr: Option<&str>,
    frame_image_addr: Option<&str>,
    debug_images: &[DebugImage],
) -> Option<(String, u64)> {
    let instruction_addr = parse_hex_address(instruction_addr?).ok()?;
    let debug_image = find_debug_image(instruction_addr, frame_image_addr, debug_images).ok()?;
    let relative_addr = calculate_relative_addr(instruction_addr, debug_image).ok()?;
    Some((debug_image.debug_id.clone(), relative_addr))
}

#[cfg(test)]
mod test {
    use super::*;

    fn image_at(debug_id: &str, image_addr: u64) -> DebugImage {
        DebugImage {
            debug_id: debug_id.to_string(),
            image_addr: format!("0x{image_addr:x}"),
            image_vmaddr: None,
            image_size: Some(0x10000),
            code_file: None,
            image_type: None,
            arch: None,
        }
    }

    #[test]
    fn test_parse_hex_address_with_0x_prefix() {
        assert_eq!(parse_hex_address("0x100000000").unwrap(), 0x100000000);
        assert_eq!(parse_hex_address("0X100000000").unwrap(), 0x100000000);
    }

    #[test]
    fn test_parse_hex_address_without_prefix() {
        assert_eq!(parse_hex_address("100000000").unwrap(), 0x100000000);
        assert_eq!(parse_hex_address("deadbeef").unwrap(), 0xdeadbeef);
    }

    #[test]
    fn test_parse_hex_address_with_whitespace() {
        assert_eq!(parse_hex_address("  0x100000000  ").unwrap(), 0x100000000);
    }

    #[test]
    fn test_parse_hex_address_invalid() {
        assert!(parse_hex_address("not_hex").is_err());
        assert!(parse_hex_address("0xGGGG").is_err());
    }

    #[test]
    fn test_calculate_relative_addr() {
        let result = calculate_relative_addr(0x100004000, &image_at("test-uuid", 0x100000000));
        assert_eq!(result.unwrap(), 0x4000);
    }

    #[test]
    fn test_calculate_relative_addr_below_image_base() {
        let result = calculate_relative_addr(0x100, &image_at("test-uuid", 0x100000000));
        assert!(matches!(result, Err(NativeError::InvalidAddress(_))));
    }

    #[test]
    fn test_find_debug_image_by_image_addr() {
        let debug_images = vec![
            image_at("other-uuid", 0x200000000),
            image_at("matching-uuid", 0x100000000),
        ];

        let result = find_debug_image(0x100004000, Some("0x100000000"), &debug_images).unwrap();
        assert_eq!(result.debug_id, "matching-uuid");
    }

    #[test]
    fn test_find_debug_image_by_address_range() {
        let debug_images = vec![image_at("range-match", 0x100000000)];

        let result = find_debug_image(0x100004000, None, &debug_images).unwrap();
        assert_eq!(result.debug_id, "range-match");
    }

    #[test]
    fn test_find_debug_image_no_match() {
        let debug_images = vec![image_at("some-uuid", 0x100000000)];

        let result = find_debug_image(0x300000000, None, &debug_images);
        assert!(matches!(result, Err(NativeError::NoMatchingDebugImage)));
    }

    #[test]
    fn test_launch_invariant_addr() {
        let images = [image_at("uuid-build-1", 0x104f00000)];
        let result = launch_invariant_addr(Some("0x104f04000"), Some("0x104f00000"), &images);
        assert_eq!(result, Some(("uuid-build-1".to_string(), 0x4000)));
    }

    #[test]
    fn test_launch_invariant_addr_without_matching_image() {
        let result = launch_invariant_addr(Some("0x104f04000"), None, &[]);
        assert_eq!(result, None);
    }
}
