use super::*;

/// `host.scene.set/patch/clear/info`. Columns arrive as typed arrays (or
/// plain number arrays) and are copied straight out of the script's memory.
pub(super) fn scene_request(
    scenes: &RefCell<crate::scene::Scenes>,
    op: &str,
    name: &str,
    columns: &rquickjs::Value<'_>,
) -> Result<Value, String> {
    use crate::scene::{Columns, Scene};
    if name.is_empty() || name.len() > 64 {
        return Err("Name a scene with 1–64 characters".into());
    }
    let object = columns.as_object();
    let field = |key: &str| object.and_then(|o| o.get::<_, rquickjs::Value>(key).ok());
    let mut all = scenes.borrow_mut();
    let result = match op {
        "set" => {
            let columns = Columns {
                x: numbers(field("x"))?,
                y: numbers(field("y"))?,
                size: numbers(field("size"))?,
                group: numbers(field("group"))?
                    .into_iter()
                    .map(|g| g as u8)
                    .collect(),
                palette: strings(field("palette"))?,
                edges: integers(field("edges"))?,
                labels: strings(field("labels"))?,
            };
            let scene = Scene::new(columns)?;
            let info = json!({"nodes": scene.len(), "edges": scene.edge_count()});
            all.scenes.insert(name.to_owned(), Rc::new(scene));
            info
        }
        "patch" => {
            let scene = all
                .scenes
                .get_mut(name)
                .ok_or("Set the scene before patching it")?;
            let indices = integers(field("indices"))?;
            let groups: Vec<u8> = numbers(field("group"))?
                .into_iter()
                .map(|g| g as u8)
                .collect();
            Rc::get_mut(scene)
                .ok_or("This scene is being drawn; patch it again next frame")?
                .patch(
                    &indices,
                    &numbers(field("x"))?,
                    &numbers(field("y"))?,
                    &groups,
                    &numbers(field("size"))?,
                )?;
            json!({"nodes": scene.len()})
        }
        "clear" => json!({"cleared": all.scenes.remove(name).is_some()}),
        "info" => match all.scenes.get(name) {
            Some(s) => json!({"nodes": s.len(), "edges": s.edge_count(),
                "bounds": [s.bounds.x0, s.bounds.y0, s.bounds.x1, s.bounds.y1]}),
            None => Value::Null,
        },
        _ => return Err("Unknown scene operation".into()),
    };
    if op != "info" {
        all.version += 1;
    }
    Ok(result)
}

/// A numeric column: a typed array (copied as raw memory) or an array.
fn numbers(value: Option<rquickjs::Value<'_>>) -> Result<Vec<f32>, String> {
    use rquickjs::TypedArray;
    let Some(value) = value.filter(|v| !v.is_undefined() && !v.is_null()) else {
        return Ok(Vec::new());
    };
    macro_rules! typed {
        ($t:ty) => {
            if let Ok(array) = TypedArray::<$t>::from_value(value.clone()) {
                return Ok(raw::<$t>(&array).into_iter().map(|v| v as f32).collect());
            }
        };
    }
    typed!(f32);
    typed!(f64);
    typed!(u8);
    typed!(u16);
    typed!(u32);
    typed!(i32);
    let list: Vec<f64> = rquickjs::FromJs::from_js(value.ctx(), value.clone())
        .map_err(|_| "Scene columns must be typed arrays or arrays of numbers".to_owned())?;
    Ok(list.into_iter().map(|v| v as f32).collect())
}

/// An index column, exact for every node index.
fn integers(value: Option<rquickjs::Value<'_>>) -> Result<Vec<u32>, String> {
    use rquickjs::TypedArray;
    let Some(value) = value.filter(|v| !v.is_undefined() && !v.is_null()) else {
        return Ok(Vec::new());
    };
    if let Ok(array) = TypedArray::<u32>::from_value(value.clone()) {
        return Ok(raw::<u32>(&array));
    }
    if let Ok(array) = TypedArray::<i32>::from_value(value.clone()) {
        return Ok(raw::<i32>(&array)
            .into_iter()
            .map(|v| v.max(0) as u32)
            .collect());
    }
    let list: Vec<f64> = rquickjs::FromJs::from_js(value.ctx(), value.clone()).map_err(|_| {
        "Scene edges and indices must be a Uint32Array or an array of integers".to_owned()
    })?;
    Ok(list.into_iter().map(|v| v.max(0.) as u32).collect())
}

fn strings(value: Option<rquickjs::Value<'_>>) -> Result<Vec<String>, String> {
    let Some(value) = value.filter(|v| !v.is_undefined() && !v.is_null()) else {
        return Ok(Vec::new());
    };
    rquickjs::FromJs::from_js(value.ctx(), value.clone())
        .map_err(|_| "Scene labels and palette must be arrays of strings".to_owned())
}

/// A typed array's elements, read from its backing memory in one pass.
fn raw<T: Copy>(array: &rquickjs::TypedArray<'_, T>) -> Vec<T> {
    let Some(bytes) = array.as_raw() else {
        return Vec::new();
    };
    let size = std::mem::size_of::<T>();
    // SAFETY: `as_raw` is the live view's backing bytes, valid while
    // `array` is borrowed; reads are unaligned-safe and copy out.
    let bytes = unsafe { bytes.as_ref() };
    bytes
        .chunks_exact(size)
        .map(|chunk| unsafe { std::ptr::read_unaligned(chunk.as_ptr() as *const T) })
        .collect()
}
