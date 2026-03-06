# Better Blender MCP Milestone Board

## Program Goals
- Deliver a production-ready MCP server for local Blender control on macOS, Windows, and Linux.
- Provide a fast onboarding path: install, enable add-on, connect client, run first tool.
- Guarantee safe execution boundaries for local file operations and code execution.

## Milestones at a Glance
| Milestone | Duration | Primary Output | Exit Gate |
|---|---:|---|---|
| M0: Foundations | Week 1 | Repo, quality gates, architecture spec | CI green on lint/type/unit smoke |
| M1: Bridge Runtime | Week 2 | Blender add-on + IPC bridge + command queue | End-to-end health-check tool works |
| M2: Core Tooling | Weeks 3-4 | Scene/object/material/camera/render/import/export tools | 80% of v1 tools integration-tested |
| M3: Security + UX | Week 5 | Auth, allowlists, unsafe-mode gating, doctor/install commands | Security tests pass |
| M4: Hardening + Docs | Weeks 6-7 | Cross-platform test matrix + complete docs | Fresh-machine setup validated on 3 OSes |
| M5: Release | Week 8 | Stable tag and installable package | Beta feedback addressed, release checklist complete |

## Workstream Owners
- **Platform/Server**: MCP protocol, transport, tool schemas.
- **Blender Bridge**: Add-on lifecycle, main-thread executor, bpy adapters.
- **Quality**: CI, tests, compatibility matrix.
- **DX/Docs**: installer, doctor, quickstart, troubleshooting.

## Ticket Backlog

### M0: Foundations (Week 1)

#### BB-001 Repo bootstrap
- Scope: Create package layout, `pyproject.toml`, editable install path, entrypoint CLI.
- Depends on: none
- DoD:
  - `pip install -e .` succeeds.
  - `better-blender-mcp --help` works.
  - Repository contains `src/`, `tests/`, `docs/`, `blender_addon/`.

#### BB-002 Quality tooling
- Scope: Add `ruff`, `mypy`, `pytest`, `pre-commit`.
- Depends on: BB-001
- DoD:
  - `ruff check .`, `mypy src`, `pytest` run in CI.
  - pre-commit hooks configured and documented.

#### BB-003 Architecture + protocol spec
- Scope: Define bridge JSON-RPC envelope, auth model, error envelope, job lifecycle.
- Depends on: BB-001
- DoD:
  - `docs/spec.md` exists with message schemas.
  - v1 capability negotiation documented.

### M1: Bridge Runtime (Week 2)

#### BB-010 Blender add-on skeleton
- Scope: Add register/unregister, preferences panel, start/stop operator.
- Depends on: BB-003
- DoD:
  - Add-on install/enable works on Blender 3.4.1+
  - UI toggles bridge service.

#### BB-011 Main-thread execution queue
- Scope: Use `bpy.app.timers` to drain command queue on main thread.
- Depends on: BB-010
- DoD:
  - Queue handles at least 100 sequential commands without crash.
  - Unit/integration test confirms execution occurs on main thread.

#### BB-012 IPC server + token auth
- Scope: Localhost WebSocket listener in add-on, token validation, heartbeat.
- Depends on: BB-010
- DoD:
  - Rejects unauthenticated requests.
  - Bridge returns health metadata (Blender version, file path).

#### BB-013 MCP server handshake
- Scope: MCP server startup, bridge client, `get_blender_status` tool.
- Depends on: BB-011, BB-012
- DoD:
  - MCP client lists tools and executes health check end-to-end.

### M2: Core Tooling (Weeks 3-4)

#### BB-020 Scene and object tools
- Scope: `new_scene`, `list_objects`, `get_object_info`, `create_primitive`, `delete_object`, `set_transform`.
- Depends on: BB-013
- DoD:
  - Tools validate inputs with strict schemas.
  - Integration tests verify scene mutations.

#### BB-021 Material tools
- Scope: `create_material`, `assign_material`, `set_principled_params`.
- Depends on: BB-020
- DoD:
  - Node tree creation deterministic and idempotent where possible.
  - Material assignment test coverage for mesh and non-mesh failures.

#### BB-022 Camera and light tools
- Scope: `create_camera`, `set_active_camera`, `create_light`, light params.
- Depends on: BB-020
- DoD:
  - Basic render setup achievable via tools only.

#### BB-023 Render job tools
- Scope: `render_still`, `render_animation`, `get_job_status`, `cancel_job`.
- Depends on: BB-022
- DoD:
  - Long jobs return `job_id` and pollable status.
  - Cancel path tested.

#### BB-024 Import/export tools
- Scope: FBX/OBJ/GLTF/USD import/export wrappers.
- Depends on: BB-020
- DoD:
  - Feature flags by operator availability.
  - Path handling normalized across OSes.

### M3: Security + UX (Week 5)

#### BB-030 Authorization and safe modes
- Scope: Modes `read_only`, `normal`, `unsafe`; reject restricted ops in lower modes.
- Depends on: BB-024
- DoD:
  - Policy matrix tests enforce mode behavior.

#### BB-031 Path security
- Scope: Path allowlists and traversal protections for file operations.
- Depends on: BB-024
- DoD:
  - Rejects path traversal attempts.
  - Per-op error messages actionable.

#### BB-032 Audit logging
- Scope: Structured logs for every tool call and bridge action.
- Depends on: BB-013
- DoD:
  - Logs include request id, tool name, status, duration.

#### BB-033 Installer and doctor
- Scope: `install-addon`, `doctor`, `print-config` commands.
- Depends on: BB-013
- DoD:
  - Fresh machine diagnostic report includes Blender detection + bridge status.

### M4: Hardening + Docs (Weeks 6-7)

#### BB-040 Cross-platform test matrix
- Scope: GitHub Actions matrix: OS (macOS/ubuntu/windows) + Python versions.
- Depends on: BB-033
- DoD:
  - CI matrix green with flaky test budget <= 2%.

#### BB-041 Integration harness
- Scope: headless Blender orchestration for automated tool tests.
- Depends on: BB-023
- DoD:
  - Nightly integration run executes core workflow scenarios.

#### BB-042 Documentation set
- Scope: quickstart, operations guide, troubleshooting, API reference.
- Depends on: BB-033
- DoD:
  - New user can complete first render in under 10 minutes following docs.

### M5: Release (Week 8)

#### BB-050 Beta and feedback triage
- Scope: tag beta, collect issues, prioritize P0/P1 fixes.
- Depends on: BB-040, BB-042
- DoD:
  - No open P0 defects.

#### BB-051 Stable packaging and publication
- Scope: publish package, version docs, signed tag, release notes.
- Depends on: BB-050
- DoD:
  - install command works from package index.
  - release checklist completed and archived.

## Acceptance Test Catalog (Minimal)
- AT-001: Start bridge from Blender UI and pass authenticated health request.
- AT-002: Create cube, move cube, query cube info through MCP.
- AT-003: Create material, assign to cube, validate material slot.
- AT-004: Create camera/light and render still image to output path.
- AT-005: Unauthorized request is rejected.
- AT-006: Read-only mode blocks destructive ops.
- AT-007: Import OBJ then export GLTF.
- AT-008: Fresh install flow with `doctor` on each OS.

## Risks and Mitigations
- Blender thread safety: enforce main-thread queue and forbid direct worker-thread bpy calls.
- Cross-platform Blender path discovery: include auto-detect + manual override + diagnostics.
- Network safety on localhost: token auth, short-lived sessions, strict bind host.
- Operator differences by Blender version: capability checks and version-gated tool responses.

## Delivery Cadence
- Weekly planning: update milestone burndown and blocked tickets.
- Daily integration branch verification for bridge + MCP server.
- Weekly tagged preview builds during M2-M4.
