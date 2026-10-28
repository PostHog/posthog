use percent_encoding::percent_decode_str;
use url::Url;

const RESIZE_LONG_SIDE: u32 = 1024;
const MAX_SHOPIFY_DIMENSION: u32 = 5760;
type Dimensions = (Option<u32>, Option<u32>);

pub(super) fn normalize_image_size(url: &mut Url, query: Option<&str>) -> Option<String> {
    if !is_shopify_image(url) || url.path().contains("_crop_") {
        return None;
    }
    let fields: Vec<&str> = query.map_or_else(Vec::new, |query| query.split('&').collect());
    let mut width = None;
    let mut height = None;
    for field in &fields {
        let (name, value) = field.split_once('=').unwrap_or((field, ""));
        let name = percent_decode_str(name).decode_utf8().ok()?;
        match name.as_ref() {
            "width" if width.is_none() => width = Some(dimension(value)?),
            "height" if height.is_none() => height = Some(dimension(value)?),
            "v" | "format" | "cb" | "nocache" | "rnd" => {}
            _ => return None,
        }
    }
    let (stem, extension) = url.path().rsplit_once('.')?;
    let legacy_size = legacy_size(stem);
    if let Some((base, dimensions)) = legacy_size {
        if width.is_some() || height.is_some() {
            return None;
        }
        let (width, height) = normalize_dimensions(dimensions.0, dimensions.1)?;
        let width = width.map_or_else(String::new, |value| value.to_string());
        let height = height.map_or_else(String::new, |value| value.to_string());
        let path = format!("{base}_{width}x{height}.{extension}");
        url.set_path(&path);
        return None;
    }
    // Two dimensions can request a crop, whose result also depends on the original image bounds.
    if width.is_some() && height.is_some() {
        return None;
    }
    let (width, height) = normalize_dimensions(width, height)?;
    let fields: Vec<String> = fields
        .into_iter()
        .map(|field| {
            let (name, _) = field.split_once('=').unwrap_or((field, ""));
            match percent_decode_str(name).decode_utf8().ok().as_deref() {
                Some("width") => format!("{name}={}", width.unwrap()),
                Some("height") => format!("{name}={}", height.unwrap()),
                _ => field.to_string(),
            }
        })
        .collect();
    Some(fields.join("&"))
}

fn is_shopify_image(url: &Url) -> bool {
    let path = url.path();
    let Some((_, extension)) = path.rsplit_once('.') else {
        return false;
    };
    if !matches!(extension, "jpg" | "jpeg" | "png" | "webp" | "avif" | "gif") {
        return false;
    }
    if url
        .host_str()
        .and_then(|host| host.strip_suffix(".myshopify.com"))
        .is_some_and(|store| !store.is_empty() && !store.contains('.'))
    {
        return [
            "/cdn/shop/files/",
            "/cdn/shop/products/",
            "/cdn/shop/collections/",
        ]
        .iter()
        .any(|prefix| {
            path.strip_prefix(prefix)
                .is_some_and(|file| !file.contains('/'))
        });
    }
    if url.host_str() != Some("cdn.shopify.com") {
        return false;
    }
    let Some(path) = path.strip_prefix("/s/files/") else {
        return false;
    };
    let segments: Vec<&str> = path.split('/').collect();
    segments.len() >= 5
        && matches!(
            segments[segments.len() - 2],
            "files" | "products" | "collections"
        )
        && segments[..segments.len() - 2]
            .iter()
            .all(|segment| !segment.is_empty() && segment.bytes().all(|byte| byte.is_ascii_digit()))
}

fn dimension(value: &str) -> Option<u32> {
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    value
        .parse()
        .ok()
        .filter(|value| (1..=MAX_SHOPIFY_DIMENSION).contains(value))
}

fn legacy_size(stem: &str) -> Option<(&str, Dimensions)> {
    let stem = stem
        .strip_suffix("@2x")
        .or_else(|| stem.strip_suffix("@3x"))
        .unwrap_or(stem);
    let (base, size) = stem.rsplit_once('_')?;
    let named = match size {
        "pico" => Some(16),
        "icon" => Some(32),
        "thumb" => Some(50),
        "small" => Some(100),
        "compact" => Some(160),
        "medium" => Some(240),
        "large" => Some(480),
        "grande" => Some(600),
        _ => None,
    };
    let dimensions = if let Some(side) = named {
        (Some(side), Some(side))
    } else {
        let (width, height) = size.split_once('x')?;
        (
            if width.is_empty() {
                None
            } else {
                Some(dimension(width)?)
            },
            if height.is_empty() {
                None
            } else {
                Some(dimension(height)?)
            },
        )
    };
    Some((base, dimensions))
}

fn normalize_dimensions(width: Option<u32>, height: Option<u32>) -> Option<Dimensions> {
    match (width, height) {
        (Some(width), Some(height)) => {
            let (mut a, mut b) = (width, height);
            while b != 0 {
                (a, b) = (b, a % b);
            }
            let (width, height) = (width / a, height / a);
            let scale = RESIZE_LONG_SIDE / width.max(height);
            (scale > 0).then_some((Some(width * scale), Some(height * scale)))
        }
        (Some(_), None) => Some((Some(RESIZE_LONG_SIDE), None)),
        (None, Some(_)) => Some((None, Some(RESIZE_LONG_SIDE))),
        (None, None) => None,
    }
}
