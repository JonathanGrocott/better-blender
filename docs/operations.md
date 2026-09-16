# Operating Better Blender 0.5

## Setup and access

`install-addon`, `setup`, and `print-config` create a random per-user token if one
is not already present. It lives in `~/.better-blender/token`; on POSIX it is
readable only by its owner. Both processes must use the same user/state directory.
`BETTER_BLENDER_STATE_DIR` overrides that directory for both processes.
Leave Blender's **Token override** blank to use the generated token.
An existing custom token remains supported; set `BETTER_BLENDER_TOKEN` in the
MCP process to match it. The old `change-me` add-on default now uses the generated
credential, so remove old explicit `change-me` client environment values.

Add-on preferences take effect after restarting the bridge:

- **Read-only mode** rejects every method outside an explicit inspection allowlist,
  including rendering, file writes, checkpoint deletion and unsafe Python.
- **Allowed tool directory** restricts explicit input/output paths, resolving `..`
  and symlinks. Programmatic startup accepts multiple `allowed_roots`. Internal
  checkpoints, logs and render snapshots remain in managed storage.
- **Allow nonlocal binding** is required to listen outside loopback, together with
  a token at least 32 characters long. The bridge uses plain TCP; use a trusted
  network or an encrypted tunnel. It does not supply TLS.
- Unsafe Python is disabled by default and also rejected when directory
  restrictions are enabled. Tool-path restrictions are not an OS sandbox:
  dependencies, compositor outputs and scripts within Blender can have their own
  paths. Opening a file through the bridge disables its automatic Python scripts.

## Document targeting

`get_document_context` returns `session_id`, `document_id`, scene and filepath.
The document ID changes on every file load and active-scene switch, including
reopening the same file. Saving the current file does not change it.

The MCP client remembers context from successful responses and sends it with
subsequent calls. Every queued edit also captures its enqueue-time document ID.
An edit returns `DOCUMENT_CHANGED` if its target is no longer active before
execution. Inspect the new document before issuing a new edit. The bridge cannot
identify an intended document that the caller has never inspected: use
`get_document_context` before the first edit or pass its ID explicitly below.

## Safe retries

For edits that must be recoverable after connection loss:

1. Call `get_document_context` and retain `document_id`.
2. Choose a unique request ID (for example a UUID).
3. Call `execute_request(request_id, expected_document_id, method, params)`.
4. If disconnected, use `get_request_status(request_id)` or repeat the same call
   with the **same ID and arguments**. Completed calls return the recorded result;
   pending or interrupted calls return an uncertain outcome without re-execution.

Every ordinary mutation also gets a generated request ID, shown in error messages.
Python callers can read `BridgeError.request_id`. The journal fingerprints the
method and arguments; reuse with different arguments is rejected. The document
ID is an admission guard, not part of that fingerprint, so a successful file-load
operation can still be replayed after it changes the active document.

This is at-most-once admission, not a transaction or an exactly-once guarantee:
a crash during an edit may leave partial changes. Interrupted requests must be
inspected and recovered, potentially using a checkpoint, before a new edit.
Timeouts during execution do not cancel the operation. Shutdown expires queued
work and wakes its callers.

The SQLite journal persists under `requests/`, namespaced by host and port.
Keep that endpoint stable across restarts. Responses over 256 KiB are marked
`RESULT_NOT_RETAINED`; the operation still will not run twice. The journal holds
10,000 identities and refuses new mutations when full instead of forgetting old
IDs. Archive a full journal only with the bridge stopped and after retiring all
clients that could retry those IDs. Changing the state directory or endpoint, or
removing the journal, ends retry protection for its old requests.

## Checkpoints and external assets

Snapshots default to **20 files / 2 GiB**. Use `configure_checkpoint_retention`
to change limits and immediately prune oldest snapshots. New snapshots also
prune; a single snapshot larger than the byte limit is rejected. Active snapshot
files and snapshots involved in a restore are protected, so limits can temporarily
be exceeded. Inspect `within_limits` in the result.

`get_checkpoint_usage` reports managed snapshot bytes separately from metadata
and working files. `delete_checkpoint` removes the immutable snapshot and its
metadata; **restored working files are retained**, even if they exceed the limits.
Save or remove these files yourself when no longer needed.

`check_assets` checks current external references, or the saved manifest for a
checkpoint. Packed data is excluded. UDIM/tile patterns require at least one
matching file; this does not verify every sequence frame or simulation cache.
Render submission fails before starting a worker if references are missing.
Restore checks the manifest before changing the open document. Legacy snapshots
without a manifest require `allow_missing_assets=True`, as do deliberate restores
with missing references. Checkpoints reference external files; they do not bundle
or freeze those files' contents.

## Diagnostics

`get_diagnostics` remains available while the main-thread queue is occupied. It
reports queue depth/capacity, active connections, worker jobs, journal occupancy,
session/document IDs, request counters and the latest 50 failures.

Logs under `logs/` are JSON Lines, capped at 1 MiB each with three backups per
endpoint. They contain IDs, method names, outcomes and elapsed milliseconds.
Arguments, tokens, result bodies and error text are excluded. `response` timing
covers handling and queue wait; `execution` timing measures dispatch. Failure
counters count events, so one failed edit can have both event types. Logs and
counters are diagnostic rather than an audit guarantee; in-memory counters reset
on restart. Request outcomes remain in the durable journal.

## Development and verification

`commands_scene`, `commands_objects`, `commands_animation`, `commands_nodes`,
`commands_rendering`, and `commands_collections` handle Blender domains. The
bridge owns authentication, admission, policy, queueing and common validation.
Domain handlers receive the shared bridge helper context explicitly and execute
only on the main thread. Supported methods derive from the generated schemas.

Run `ruff check .`, `mypy src`, and `pytest -m 'integration or not integration'`.
The latter needs Blender and a display for the GUI test (Xvfb works on Linux).
CI exercises Blender 3.4.1, 4.2.0 and 5.0.1, plus Python and packaging on Linux,
macOS and Windows. Failure tests cover duplicate admission, response loss,
restart replay, stale queued edits, shutdown, retention and access restrictions.

## Render and bridge lifecycle (0.5.1)

Render jobs have a separate **Render Runtime Limit** in add-on preferences,
independent of the socket request timeout. The default is one hour; restart the
bridge after changing it. Programmatic startup accepts `render_timeout_seconds`.
A render that exceeds this limit ends as `timed_out`, with already-written outputs
left intact. Job status includes the configured limit.

A small supervisor runs under Blender's bundled Python interpreter. It records
admission before launching Blender and owns the worker until it exits. Cancellation,
deadlines and bridge connection loss trigger termination, escalating to a kill
after two seconds if needed. Cancellation does not require a writable job store.
If the bridge process crashes, its control pipe closes and the supervisor stops
the worker, records `interrupted` where storage permits, and removes its workspace.
This assumes the supervisor and OS remain operational; it is not protection against
arbitrary supervisor termination or a machine failure.

Temporary render snapshots live under the endpoint's job storage. Restart cleans
abandoned directories, including partial snapshots left before launch. Cross-process
leases protect directories still owned by a supervisor. Small lease files remain
to avoid races from replacing lock-file identities. Caller-owned render outputs
are never removed by this cleanup.

If saving a terminal result fails, the bridge reports a failed job and, when
applicable, a `persistence_error`; the supervisor still stops/reaps the worker and
cleans its workspace. Inspect any output files before submitting a new render.

Startup failures roll back the listener, timer, file-load callback, database and
log handles. Shutdown expires queued commands, stops render workers, waits for
request handlers, then closes the database and logging resources. Fault tests
cover failed admission, watcher startup, terminal persistence, unresponsive workers,
owner-process crashes, startup rollback and repeated start/stop cycles.
