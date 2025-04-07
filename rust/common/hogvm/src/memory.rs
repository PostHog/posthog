#[derive(Debug, Clone)]
pub struct HeapValue {
    epoch: usize,
    value: HogValue,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct HeapReference {
    idx: usize,
    epoch: usize, // Used to allow heap values to be freed, and their
}

#[derive(Default)]
pub struct VmHeap {
    inner: Vec<HeapValue>,
    freed: Vec<HeapReference>, // Indices of freed heap values, for reuse
}

impl VmHeap {
    pub fn emplace(&mut self, value: HogValue) -> Result<HeapReference, VmError> {
        let (next_idx, next_epoch) = match self.freed.pop() {
            Some(ptr) => (ptr.idx, ptr.epoch + 1),
            None => (self.inner.len(), 0),
        };

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

        // All existing references to this value are now invalid, and any use of them will result in a UseAfterFree error.
        to_free.epoch += 1;
        to_free.value = HogValue::Null;

        // This slot's now available for reuse.
        self.freed.push(ptr);
        Ok(())
    }

    pub fn get(&self, ptr: HeapReference) -> Result<&HogValue, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        Ok(&to_load.value)
    }

    pub fn get_mut(&mut self, ptr: HeapReference) -> Result<&mut HogValue, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &mut self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        Ok(&mut to_load.value)
    }

    pub fn clone(&self, ptr: HeapReference) -> Result<HogValue, VmError> {
        self.get(ptr).cloned()
    }

    pub fn store(&mut self, ptr: HeapReference, value: HogValue) -> Result<(), VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_store = &mut self.inner[ptr.idx];

        if to_store.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        to_store.value = value;
        Ok(())
    }
}
