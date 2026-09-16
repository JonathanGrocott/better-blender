# Publishing a release

The CI workflow tests every push/PR. A push of a tag named `vX.Y.Z` additionally
publishes a GitHub Release after all checks and distribution builds succeed.
Only the publication job has `contents: write` permission.

1. Update the version in `pyproject.toml`, `src/better_blender_mcp/__init__.py`, and
   the add-on's `bl_info` in `blender_addon/better_blender_bridge/__init__.py`.
2. Add `docs/releases/vX.Y.Z.md` with user-facing changes, installation links and
   migration notes. Update installation examples when appropriate.
3. Run `python scripts/check_release.py --tag vX.Y.Z`, lint, type checks and tests.
4. Commit and push the changes, then wait for main's CI to pass.
5. Create an annotated tag on that tested commit and push it:

   ```bash
   git tag -a vX.Y.Z -m "Better Blender vX.Y.Z"
   git push origin vX.Y.Z
   ```

The tag push reruns the full CI matrix. The workflow validates all version values,
builds a matching wheel/add-on ZIP with checksums, and downloads those same tested
artifacts into the release job. It creates a draft, uploads its three files,
downloads them again to verify checksums and wheel/ZIP parity, then publishes.
Release creation requires the tag to exist; the workflow never invents a tag.
Only stable `X.Y.Z` versions are currently supported.

If validation or tests fail, no release is published. If upload/verification fails,
a draft may remain. Fix infrastructure issues and rerun the failed jobs; the
publisher can resume an existing draft. It leaves an already-public release
unchanged. Never move an already-published tag or replace its assets; fix source
issues in a new version instead.

Normal branch pushes, pull requests and manual runs do not publish releases.
Manual runs can validate/build artifacts, but publication requires a tag push.
No signing certificate or PyPI credential is needed; these are unsigned GitHub
Release assets. Maintainers with push rights can create the release tag, subject
to the repository's own tag and Actions permission settings.
