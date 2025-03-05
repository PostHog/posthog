This is a reimplementation of the logic in cookielessServerHashStep.ts in the plugin-server.

If you change one implementation, make sure you change both!

These should be exactly the same, specifically these things should work the same way:
* Salt creation / management
* Hashing function
* Behaviour around identify() calls
* Everything else

This exists primarily so that the flags endpoint can function in cookieless mode.