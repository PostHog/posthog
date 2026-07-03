//! Thin adapters bridging the v2 walk's buffer-writing scrub interface (`fn(&str, &mut String) ->
//! changed`) to the crate's own leaf scrubbers (which return `Option<String>`, `None` = unchanged).
//! Keeping the walk on the crate's scrubs makes the benchmark an apples-to-apples comparison and the
//! parity test (`tests/mlhog_parity.rs`) meaningful.

use crate::blur::{blank_image_data_uri, is_image_data_uri};
use crate::context::Ctx;

fn push_opt(result: Option<String>, out: &mut String) -> bool {
    match result {
        Some(v) => {
            out.push_str(&v);
            true
        }
        None => false,
    }
}

pub fn text_into(ctx: &Ctx<'_>, s: &str, out: &mut String) -> bool {
    push_opt(crate::text::scrub_text(ctx.allow, s), out)
}

pub fn redact_emails_into(s: &str, out: &mut String) -> bool {
    push_opt(crate::text::redact_emails(s), out)
}

pub fn url_into(ctx: &Ctx<'_>, s: &str, out: &mut String) -> bool {
    push_opt(crate::url::scrub_url(ctx.allow, s), out)
}

pub fn url_authority_into(ctx: &Ctx<'_>, s: &str, out: &mut String) -> bool {
    push_opt(crate::url::scrub_url_opts(ctx.allow, s, true), out)
}

pub fn css_into(ctx: &Ctx<'_>, s: &str, out: &mut String) -> bool {
    push_opt(crate::css::rewrite(ctx, s), out)
}

/// Blur an inlined image data URI (memoized via the shared `Ctx`), falling back to a blank pixel.
/// Non-image strings are left unchanged.
pub fn inline_image_into(ctx: &Ctx<'_>, s: &str, out: &mut String) -> bool {
    if !is_image_data_uri(s) {
        return false;
    }
    out.push_str(&ctx.blur_data_uri(s).unwrap_or_else(blank_image_data_uri));
    true
}
