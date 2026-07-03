// Copied from MLHog prep/labeling/src/context.rs — bench-only. Adapted: the `config: &Config`
// field is dropped (v2 only reads `ctx.allow`; the redaction marks are associated consts).

use crate::mlhog::dict::AllowLists;

#[derive(Debug)]
pub struct Ctx<'a> {
    pub allow: &'a AllowLists,
}

impl<'a> Ctx<'a> {
    pub fn new(allow: &'a AllowLists) -> Self {
        Self { allow }
    }
}
