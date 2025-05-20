use crate::{error::VmError, values::HogLiteral};

#[derive(Debug, Clone)]
pub struct HeapValue {
    epoch: usize,
    value: HogLiteral,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct HeapReference {
    idx: usize,
    epoch: usize, // Used to allow heap values to be freed, and their
}

#[derive(Default)]
pub struct VmHeap {
    inner: Vec<HeapValue>,
    // TODO - we never actually free heap allocations, because we don't do reference counting anywhere. We could
    // improve this. Right now our heap is append-only
    freed: Vec<HeapReference>, // Indices of freed heap values, for reuse

    pub(crate) current_bytes: usize, // Pub: the vm occasionally directly writes to this
    max_bytes: usize,
}

/// All heap functions are pub(crate) for now, because function authors should never use them directly,
/// going through either the VM or the `HogValue` interface instead
impl VmHeap {
    pub(crate) fn new(max_bytes: usize) -> Self {
        Self {
            inner: Vec::new(),
            freed: Vec::new(),
            current_bytes: 0,
            max_bytes,
        }
    }

    fn assert_can_allocate(&self, new_bytes: usize) -> Result<(), VmError> {
        if self.current_bytes.saturating_add(new_bytes) > self.max_bytes {
            Err(VmError::OutOfResource("Heap Memory".to_string()))
        } else {
            Ok(())
        }
    }

    pub(crate) fn emplace(&mut self, value: HogLiteral) -> Result<HeapReference, VmError> {
        self.assert_can_allocate(value.size())?;

        let (next_idx, next_epoch) = match self.freed.pop() {
            Some(ptr) => (ptr.idx, ptr.epoch + 1),
            None => (self.inner.len(), 0),
        };

        self.current_bytes = self.current_bytes.saturating_add(value.size());

        if self.inner.len() <= next_idx {
            self.inner.push(HeapValue {
                epoch: next_epoch,
                value,
            });
        } else {
            self.inner[next_idx] = HeapValue {
                epoch: next_epoch,
                value,
            };
        }

        Ok(HeapReference {
            idx: next_idx,
            epoch: next_epoch,
        })
    }

    pub(crate) fn get(&self, ptr: HeapReference) -> Result<&HogLiteral, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        Ok(&to_load.value)
    }

    // NOTE - accessing mutable references to heap values bypasses size counts, which can let
    // us allocate more than the strict limit. We assert the limits in places we use get_mut,
    // by calling assert_can_allocate above
    pub(crate) fn get_mut(&mut self, ptr: HeapReference) -> Result<&mut HogLiteral, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &mut self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        Ok(&mut to_load.value)
    }
}
