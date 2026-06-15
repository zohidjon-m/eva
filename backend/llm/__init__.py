"""Eva LLM subsystem — supervise llama-server and stream tokens from it.

This package is the heart of Eva (Process 3 in the architecture): the native
``llama-server`` process and the async client that streams Gemma's tokens back
to the backend. Phase 1 wires only chat streaming; vault capture, the persona
prompt, and the UI arrive in later phases.
"""
