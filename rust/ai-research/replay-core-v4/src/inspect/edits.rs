//! Where the writer changes a block's bytes, by position, so that it copies each event once and searches it for nothing.

use std::ops::Range;

use super::css::CssEdit;
use super::srcset::SrcsetSlot;
use crate::bytescan::Span;
use crate::scan::cv::Expansion;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum EditSource {
    Payload,
    /// A decoded `cv` string, by its span in the payload. The writer decodes it again to the same bytes.
    Field(Span),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Slot {
    /// A URL attribute of an image slot. The writer writes the URL's reference, its decline marker, or the URL without its credentials.
    Url,
    Srcset(SrcsetSlot),
    Css(CssEdit),
    /// A URL attribute that shows no image, such as a link's `href`. No fetch takes it, so the writer keeps it without
    /// its credentials.
    Link(LinkForm),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkForm {
    Url,
    /// Candidates with descriptors, as `imagesrcset` holds them.
    Srcset,
    /// URLs apart by whitespace, as `ping` and `attributionsrc` hold them.
    Urls,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Edit {
    pub source: EditSource,
    /// The JSON string the slot holds.
    pub value: Span,
    pub slot: Slot,
}

/// The edits of one event, by its position in its block.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EventEdits {
    pub event: u32,
    /// Sorted by source and position, one per JSON string.
    pub edits: Vec<Edit>,
}

impl EventEdits {
    /// A string that is an image slot and also holds a link, such as a picture source's srcset, keeps the image slot.
    pub fn new(event: u32, mut edits: Vec<Edit>) -> Self {
        edits.sort_by_key(|edit| {
            let link = matches!(edit.slot, Slot::Link(_));
            (edit.source, edit.value.0, link)
        });
        edits.dedup_by_key(|edit| (edit.source, edit.value));
        Self { event, edits }
    }
}

/// The buffers an event's walk reads, by address, so that a slot names the one it is in.
#[derive(Debug, Clone, Default)]
pub struct Buffers {
    payload: Range<usize>,
    fields: Vec<(Range<usize>, Span)>,
}

fn addresses(bytes: &[u8]) -> Range<usize> {
    let start = bytes.as_ptr() as usize;
    start..start + bytes.len()
}

impl Buffers {
    pub fn new(payload: &[u8], expansion: &Expansion) -> Self {
        let fields = match expansion {
            Expansion::Decoded(fields) => fields
                .iter()
                .filter_map(|field| Some((addresses(field.json.as_deref()?), field.span)))
                .collect(),
            _ => Vec::new(),
        };
        Self {
            payload: addresses(payload),
            fields,
        }
    }

    pub fn source_of(&self, bytes: &[u8]) -> Option<EditSource> {
        let bytes = addresses(bytes);
        if bytes == self.payload {
            return Some(EditSource::Payload);
        }
        self.fields
            .iter()
            .find(|(field, _)| *field == bytes)
            .map(|&(_, span)| EditSource::Field(span))
    }
}
