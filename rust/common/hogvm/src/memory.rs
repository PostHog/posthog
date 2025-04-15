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
    // improve this.
    freed: Vec<HeapReference>, // Indices of freed heap values, for reuse

    pub current_bytes: usize,
    max_bytes: usize,
}

impl VmHeap {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            inner: Vec::new(),
            freed: Vec::new(),
            current_bytes: 0,
            max_bytes,
        }
    }

    pub fn assert_can_allocate(&self, new_bytes: usize) -> Result<(), VmError> {
        if self.current_bytes.saturating_add(new_bytes) > self.max_bytes {
            Err(VmError::OutOfMemory)
        } else {
            Ok(())
        }
    }

    pub fn emplace(&mut self, value: HogLiteral) -> Result<HeapReference, VmError> {
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

    pub fn free(&mut self, ptr: HeapReference) -> Result<(), VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_free = &mut self.inner[ptr.idx];

        if to_free.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        self.current_bytes = self.current_bytes.saturating_sub(to_free.value.size());

        // All existing references to this value are now invalid, and any use of them will result in a UseAfterFree error.
        to_free.epoch += 1;
        to_free.value = HogLiteral::Null;

        // This slot's now available for reuse.
        self.freed.push(ptr);
        Ok(())
    }

    pub fn get(&self, ptr: HeapReference) -> Result<&HogLiteral, VmError> {
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
    pub fn get_mut(&mut self, ptr: HeapReference) -> Result<&mut HogLiteral, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &mut self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        Ok(&mut to_load.value)
    }

    pub fn clone(&self, ptr: HeapReference) -> Result<HogLiteral, VmError> {
        self.get(ptr).cloned()
    }

    pub fn replace(&mut self, ptr: HeapReference, value: HogLiteral) -> Result<(), VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let byte_change = value
            .size()
            .saturating_sub(self.inner[ptr.idx].value.size()); // 0, if the new value is smaller than the old one
        self.assert_can_allocate(byte_change)?;

        let to_store = &mut self.inner[ptr.idx];

        if to_store.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        self.current_bytes = self
            .current_bytes
            .saturating_sub(to_store.value.size())
            .saturating_add(value.size());

        to_store.value = value;
        Ok(())
    }
}
