//! Brotli on the C encoder, with an allocator that keeps the encoder's large allocations between blocks. The
//! encoder's hash table has a fixed size for a quality, and the input's hashes choose where it is written. From the
//! system allocator it is new memory for each encoder, so a block far smaller than the table still makes the kernel
//! map and clear most of it.

use std::alloc::{alloc, dealloc, handle_alloc_error, Layout};
use std::ffi::c_void;
use std::io::{self, Write};
use std::ptr::{self, NonNull};
use std::sync::{Mutex, PoisonError};

use brotlic_sys::{
    BrotliEncoderCompressStream, BrotliEncoderCreateInstance, BrotliEncoderDestroyInstance,
    BrotliEncoderHasMoreOutput, BrotliEncoderIsFinished, BrotliEncoderOperation,
    BrotliEncoderOperation_BROTLI_OPERATION_FINISH,
    BrotliEncoderOperation_BROTLI_OPERATION_PROCESS, BrotliEncoderParameter,
    BrotliEncoderParameter_BROTLI_PARAM_LARGE_WINDOW, BrotliEncoderParameter_BROTLI_PARAM_LGWIN,
    BrotliEncoderParameter_BROTLI_PARAM_QUALITY, BrotliEncoderSetParameter, BrotliEncoderState,
    BrotliEncoderTakeOutput,
};

/// The encoder frees memory without its size, so the size sits in a header that keeps the alignment of `malloc`.
const HEADER_BYTES: usize = 16;

const POOLED_MIN_BYTES: usize = 1024 * 1024;

/// Past this the allocation kept longest goes, so a size that no encoder asks for again leaves the pool.
const POOL_MAX_BYTES: usize = 256 * 1024 * 1024;

struct Kept {
    start: NonNull<u8>,
    bytes: usize,
}

// SAFETY: the pool alone owns a kept allocation.
unsafe impl Send for Kept {}

struct Pool {
    kept: Mutex<(Vec<Kept>, usize)>,
}

static POOL: Pool = Pool::new();

fn layout(bytes: usize) -> Layout {
    Layout::from_size_align(bytes, HEADER_BYTES).expect("an allocation size the encoder asked for")
}

impl Pool {
    const fn new() -> Self {
        Self {
            kept: Mutex::new((Vec::new(), 0)),
        }
    }

    fn take(&self, bytes: usize) -> Option<NonNull<u8>> {
        let mut kept = self.kept.lock().unwrap_or_else(PoisonError::into_inner);
        let index = kept.0.iter().rposition(|kept| kept.bytes == bytes)?;
        kept.1 -= bytes;
        Some(kept.0.remove(index).start)
    }

    fn keep(&self, start: NonNull<u8>, bytes: usize) {
        let mut evicted = Vec::new();
        {
            let mut kept = self.kept.lock().unwrap_or_else(PoisonError::into_inner);
            kept.0.push(Kept { start, bytes });
            kept.1 += bytes;
            while kept.1 > POOL_MAX_BYTES {
                let oldest = kept.0.remove(0);
                kept.1 -= oldest.bytes;
                evicted.push(oldest);
            }
        }
        for Kept { start, bytes } in evicted {
            // SAFETY: `allocate` made this allocation with this layout.
            // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
            unsafe { dealloc(start.as_ptr(), layout(bytes)) };
        }
    }
}

extern "C" fn allocate(opaque: *mut c_void, size: usize) -> *mut c_void {
    let Some(bytes) = size.checked_add(HEADER_BYTES) else {
        return ptr::null_mut();
    };
    // SAFETY: `opaque` is the pool `Encoder::new` gave the encoder. An allocation holds the header and then `size`.
    // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
    unsafe {
        let pooled = (size >= POOLED_MIN_BYTES)
            .then(|| (*opaque.cast_const().cast::<Pool>()).take(bytes))
            .flatten();
        let start = pooled.unwrap_or_else(|| {
            let layout = layout(bytes);
            NonNull::new(alloc(layout)).unwrap_or_else(|| handle_alloc_error(layout))
        });
        #[cfg(test)]
        start.as_ptr().write_bytes(0xa5, bytes);
        start.as_ptr().cast::<usize>().write(bytes);
        start.as_ptr().add(HEADER_BYTES).cast()
    }
}

extern "C" fn free(opaque: *mut c_void, address: *mut c_void) {
    let Some(address) = NonNull::new(address.cast::<u8>()) else {
        return;
    };
    // SAFETY: the encoder frees only what `allocate` returned, which is the header past an allocation that starts
    // with its size. `opaque` is the pool `Encoder::new` gave the encoder.
    // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
    unsafe {
        let start = address.sub(HEADER_BYTES);
        let bytes = start.as_ptr().cast::<usize>().read();
        if bytes - HEADER_BYTES >= POOLED_MIN_BYTES {
            (*opaque.cast_const().cast::<Pool>()).keep(start, bytes);
        } else {
            dealloc(start.as_ptr(), layout(bytes));
        }
    }
}

struct Encoder(NonNull<BrotliEncoderState>);

impl Encoder {
    fn new(pool: &'static Pool) -> io::Result<Self> {
        let opaque = ptr::from_ref(pool).cast_mut().cast::<c_void>();
        // SAFETY: the allocator is valid on any thread, and its pool lives as long as the process.
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        let state = unsafe { BrotliEncoderCreateInstance(Some(allocate), Some(free), opaque) };
        NonNull::new(state)
            .map(Self)
            .ok_or_else(|| io::Error::other("no brotli encoder"))
    }

    fn set(&self, parameter: BrotliEncoderParameter, value: u32) -> io::Result<()> {
        // SAFETY: the state is a live encoder, here and in every call below.
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        if unsafe { BrotliEncoderSetParameter(self.0.as_ptr(), parameter, value) } == 0 {
            return Err(io::Error::other("the brotli encoder refused a setting"));
        }
        Ok(())
    }
}

impl Drop for Encoder {
    fn drop(&mut self) {
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        unsafe { BrotliEncoderDestroyInstance(self.0.as_ptr()) };
    }
}

/// Writes the stream a `brotlic::CompressorWriter` with the same settings writes. Each write is one call of the
/// encoder, because the encoder chooses its hash from the size of the first.
pub struct BlockEncoder<W: Write> {
    encoder: Encoder,
    out: W,
}

impl<W: Write> BlockEncoder<W> {
    pub fn new(quality: u32, window_bits: u32, out: W) -> io::Result<Self> {
        Self::in_pool(&POOL, quality, window_bits, out)
    }

    fn in_pool(pool: &'static Pool, quality: u32, window_bits: u32, out: W) -> io::Result<Self> {
        let encoder = Encoder::new(pool)?;
        encoder.set(BrotliEncoderParameter_BROTLI_PARAM_QUALITY, quality)?;
        encoder.set(BrotliEncoderParameter_BROTLI_PARAM_LGWIN, window_bits)?;
        encoder.set(BrotliEncoderParameter_BROTLI_PARAM_LARGE_WINDOW, 0)?;
        Ok(Self { encoder, out })
    }

    fn step(&mut self, input: &[u8], operation: BrotliEncoderOperation) -> io::Result<usize> {
        let state = self.encoder.0.as_ptr();
        let mut next_in = input.as_ptr();
        let mut available_in = input.len();
        let mut available_out = 0;
        // SAFETY: `next_in` points at `available_in` bytes. With no room for output, the encoder keeps it.
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        let done = unsafe {
            BrotliEncoderCompressStream(
                state,
                operation,
                &mut available_in,
                &mut next_in,
                &mut available_out,
                ptr::null_mut(),
                ptr::null_mut(),
            )
        };
        if done == 0 {
            return Err(io::Error::other("the brotli encoder failed"));
        }
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        while unsafe { BrotliEncoderHasMoreOutput(state) } != 0 {
            // SAFETY: the slice is the encoder's buffer, which is valid until the next call on the encoder.
            // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
            let output = unsafe {
                let mut size = 0;
                let output = BrotliEncoderTakeOutput(state, &mut size);
                std::slice::from_raw_parts(output, size)
            };
            self.out.write_all(output)?;
        }
        Ok(input.len() - available_in)
    }

    pub fn finish(mut self) -> io::Result<W> {
        self.step(&[], BrotliEncoderOperation_BROTLI_OPERATION_FINISH)?;
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        while unsafe { BrotliEncoderIsFinished(self.encoder.0.as_ptr()) } == 0 {
            self.step(&[], BrotliEncoderOperation_BROTLI_OPERATION_FINISH)?;
        }
        Ok(self.out)
    }
}

impl<W: Write> Write for BlockEncoder<W> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.step(buf, BrotliEncoderOperation_BROTLI_OPERATION_PROCESS)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.out.flush()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const QUALITY: u8 = 9;
    const WINDOW_BITS: u8 = 22;

    fn text(bytes: usize, seed: u64) -> Vec<u8> {
        let mut state = seed;
        let mut out = Vec::with_capacity(bytes + 64);
        while out.len() < bytes {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            let word = (state >> 33) % 4096;
            out.extend_from_slice(
                format!("{{\"id\":{word},\"tag\":\"div{}\"}},", word % 97).as_bytes(),
            );
        }
        out.truncate(bytes);
        out
    }

    fn reference(writes: &[&[u8]]) -> Vec<u8> {
        let encoder = brotlic::BrotliEncoderOptions::new()
            .quality(brotlic::Quality::new(QUALITY).unwrap())
            .window_size(brotlic::WindowSize::new(WINDOW_BITS).unwrap())
            .build()
            .unwrap();
        let mut writer = brotlic::CompressorWriter::with_encoder(encoder, Vec::new());
        for write in writes {
            writer.write_all(write).unwrap();
        }
        writer.into_inner().unwrap()
    }

    fn pooled(pool: &'static Pool, writes: &[&[u8]]) -> Vec<u8> {
        let mut encoder =
            BlockEncoder::in_pool(pool, u32::from(QUALITY), u32::from(WINDOW_BITS), Vec::new())
                .unwrap();
        for write in writes {
            encoder.write_all(write).unwrap();
        }
        encoder.finish().unwrap()
    }

    /// A test encoder's memory starts as `0xa5` bytes, so a stream that needed cleared memory would differ.
    #[test]
    fn writes_the_stream_of_the_reference_encoder_from_reused_memory() {
        let small = text(3_000, 1);
        let block = text(300_000, 2);
        // A first write of a megabyte or more selects another hash.
        let large = text(3 * 1024 * 1024, 3);
        let cases: [&[&[u8]]; 6] = [
            &[],
            &[&small],
            &[&block[..256 * 1024], &block[256 * 1024..]],
            &[&large],
            &[&large[..1024], &large[1024..]],
            &[&small, &block, &small],
        ];
        let pool: &'static Pool = Box::leak(Box::new(Pool::new()));
        for round in 0..2 {
            for (index, writes) in cases.iter().enumerate() {
                assert_eq!(
                    pooled(pool, writes),
                    reference(writes),
                    "case {index}, round {round}"
                );
            }
        }
        let kept = pool.kept.lock().unwrap();
        assert!(!kept.0.is_empty() && kept.1 <= POOL_MAX_BYTES);
    }
}
