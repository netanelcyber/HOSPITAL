//! Raw C-ABI surface for embedding in a single self-contained HTML page.
//!
//! `wasm-bindgen` generates a JavaScript glue file that must ship alongside the
//! `.wasm`. That is fine for a bundler, but it defeats a one-file deployment.
//! This module exposes a flat pointer/length ABI that plain
//! `WebAssembly.instantiate` can drive with no glue at all, so the whole
//! application fits in a single HTML document.
//!
//! Memory discipline: JavaScript calls `penux_alloc` to obtain a buffer, writes
//! into `memory`, then passes the pointer back. Every allocation is tracked so
//! `penux_free` can reconstruct the original `Vec` layout — WebAssembly has no
//! allocator introspection, and freeing with a wrong length is undefined
//! behaviour rather than a caught error.

use crate::Bundle;
use std::cell::RefCell;
use std::collections::HashMap;

thread_local! {
    static BUNDLE: RefCell<Option<Bundle>> = const { RefCell::new(None) };
    static ALLOCATIONS: RefCell<HashMap<usize, usize>> = RefCell::new(HashMap::new());
    static LAST_ERROR: RefCell<String> = const { RefCell::new(String::new()) };
}

fn set_error(message: impl Into<String>) {
    LAST_ERROR.with(|slot| *slot.borrow_mut() = message.into());
}

/// Reserve `len` bytes and return a pointer into linear memory.
#[no_mangle]
pub extern "C" fn penux_alloc(len: usize) -> *mut u8 {
    let mut buffer = Vec::<u8>::with_capacity(len);
    let ptr = buffer.as_mut_ptr();
    std::mem::forget(buffer);
    ALLOCATIONS.with(|map| map.borrow_mut().insert(ptr as usize, len));
    ptr
}

/// Release a buffer previously returned by `penux_alloc`.
#[no_mangle]
pub extern "C" fn penux_free(ptr: *mut u8) {
    let capacity = ALLOCATIONS.with(|map| map.borrow_mut().remove(&(ptr as usize)));
    if let Some(capacity) = capacity {
        // Reconstructed with the recorded capacity; a mismatched value here
        // corrupts the allocator silently.
        unsafe { drop(Vec::from_raw_parts(ptr, 0, capacity)) };
    }
}

/// Parse a model bundle from UTF-8 JSON. Returns 0 on success, -1 on failure.
///
/// # Safety
/// `ptr` must point to `len` initialized bytes inside linear memory.
#[no_mangle]
pub unsafe extern "C" fn penux_load_bundle(ptr: *const u8, len: usize) -> i32 {
    let bytes = std::slice::from_raw_parts(ptr, len);

    let text = match std::str::from_utf8(bytes) {
        Ok(text) => text,
        Err(e) => {
            set_error(format!("bundle is not valid UTF-8: {e}"));
            return -1;
        }
    };

    match serde_json::from_str::<Bundle>(text) {
        Ok(bundle) => {
            if bundle.format_version != 1 {
                set_error(format!(
                    "unsupported bundle format version {}",
                    bundle.format_version
                ));
                return -1;
            }
            BUNDLE.with(|slot| *slot.borrow_mut() = Some(bundle));
            0
        }
        Err(e) => {
            set_error(format!("bundle failed to parse: {e}"));
            -1
        }
    }
}

/// Number of features the loaded bundle expects, or 0 when none is loaded.
#[no_mangle]
pub extern "C" fn penux_n_features() -> usize {
    BUNDLE.with(|slot| {
        slot.borrow()
            .as_ref()
            .map_or(0, |b| b.feature_names.len())
    })
}

/// Score one preprocessed feature vector of `len` f64 values.
///
/// Returns a negative sentinel on error, since the ABI has no error channel and
/// a probability is always in [0, 1] — an out-of-range result is unambiguous.
///
/// # Safety
/// `ptr` must point to `len` initialized f64 values inside linear memory.
#[no_mangle]
pub unsafe extern "C" fn penux_score(ptr: *const f64, len: usize) -> f64 {
    let row = std::slice::from_raw_parts(ptr, len);

    BUNDLE.with(|slot| match slot.borrow().as_ref() {
        None => {
            set_error("no bundle loaded");
            -1.0
        }
        Some(bundle) => match bundle.score_row(row) {
            Ok(score) => score,
            Err(e) => {
                set_error(e.to_string());
                -1.0
            }
        },
    })
}

/// Apply training-time preprocessing in place over `len` f64 values.
///
/// # Safety
/// `ptr` must point to `len` initialized, writable f64 values.
#[no_mangle]
pub unsafe extern "C" fn penux_preprocess(ptr: *mut f64, len: usize) {
    let row = std::slice::from_raw_parts_mut(ptr, len);
    BUNDLE.with(|slot| {
        if let Some(bundle) = slot.borrow().as_ref() {
            bundle.preprocess(row);
        }
    });
}

/// Copy the last error message into a caller-provided buffer.
/// Returns the number of bytes written.
///
/// # Safety
/// `ptr` must point to `cap` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn penux_last_error(ptr: *mut u8, cap: usize) -> usize {
    LAST_ERROR.with(|slot| {
        let message = slot.borrow();
        let bytes = message.as_bytes();
        let n = bytes.len().min(cap);
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr, n);
        n
    })
}

/// Write the i-th feature name into a buffer. Returns bytes written, or 0.
///
/// # Safety
/// `ptr` must point to `cap` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn penux_feature_name(index: usize, ptr: *mut u8, cap: usize) -> usize {
    BUNDLE.with(|slot| match slot.borrow().as_ref() {
        Some(bundle) if index < bundle.feature_names.len() => {
            let bytes = bundle.feature_names[index].as_bytes();
            let n = bytes.len().min(cap);
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr, n);
            n
        }
        _ => 0,
    })
}
