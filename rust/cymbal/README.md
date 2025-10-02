# Cymbal, for error tracking

You throw 'em, we catch 'em.

### Terms

We use a lot of terms in this and other error tracking code, with implied meanings. Here are some of them:

- **Issue**: A group of errors, representing, ideally, one bug.
- **Error**: An event capable of producing an error fingerprint, letting it be grouped into an issue. May or may not have one or more stack traces.
- **Fingerprint**: A unique identifier for class of errors. Generated based on the error type and message, and the stack if we have one (with or without raw frames). Notably, multiple fingerprints might be 1 error, because e.g. our ability to process stack frames (based on available symbol sets) changes over time, or our fingerprinting heuristics get better. We do not encode this "class of errors" notions anywhere - it's just important to remember an "issue" might group multiple fingerprints that all have the same "unprocessed" stack trace, but different "processed" ones, or even just that were received at different time.
- **Stack trace**: You know what a stack trace is. A list of frames, raw or otherwise, most recent call last. It's important to keep in mind that some languages have the notion of `chained exceptions`, which means that a single error can have multiple stack traces.
- **Stack context**: The combination of language, operating system, runtime, dev tools, and whatever else that uniquely identifies a "type" of raw frame.
- **Raw frame**: A context specific, unprocessed frame. For some contexts, this means no symbols, for others, it might have symbols but need some other processing.
- **Frame**: A unified representation of a stack frame. Context, and pretty flexible as a result, this is what we output. Frames have all kinds of fields, and can even signal if they're the result of successful resolving or not.
- **Symbol**: A human-readable representation of the function whose calling caused a frame to be pushed. This is what we try to resolve from raw frames, where we can. Some frames don't have an associated symbol, due to e.g. anonymous closures, etc.
- **Resolving**: The generic term we use for going from a raw frame to a frame. The most important step here is symbolification, which is the process of resolving a symbol from a raw frame. That process varies a lot from context to context.
- **Symbol set**: A bunch of bytes, that can be interpreted in some way, to go from a raw frame to a symbol, provided the frame is "in" the symbol set (the function it represents is part of the set of functions whose symbols are in this set). These are highly context specific.
- **Symbol set reference**: Effectively a "pointer" to a symbol set - or the "name" of a symbol set, if you prefer. Uniquely maps a frame to a symbol set. Raw frames are required to be able to produce one of these. Again, these are highly context specific (they're a URL in frontend javascript, for example).
- **Symbol set store**: Anything that can be given a symbol set reference, and try to give back a vec of bytes. We use a layering pattern to construct a single "base" one of these, and then wrap it in internal storing, caching, etc.
