"""Upload verified assets to a draft, verify downloads, then publish the tagged release."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from check_release import ROOT, check_assets, check_version


def publish(tag, directory):
    version = check_version(tag=tag)
    assets = check_assets(directory, version)
    existing = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft"], capture_output=True, text=True
    )
    if existing.returncode == 0:
        if not json.loads(existing.stdout)["isDraft"]:
            print(f"Release {tag} is already public; leaving it unchanged")
            return
    else:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--verify-tag",
                "--draft",
                "--title",
                f"Better Blender {tag}",
                "--notes-file",
                str(ROOT / "docs/releases" / f"{tag}.md"),
            ],
            check=True,
        )
    subprocess.run(["gh", "release", "upload", tag, *map(str, assets), "--clobber"], check=True)
    with tempfile.TemporaryDirectory(prefix="bb-release-verify-") as temporary:
        subprocess.run(["gh", "release", "download", tag, "--dir", temporary], check=True)
        check_assets(Path(temporary), version)
    subprocess.run(["gh", "release", "edit", tag, "--draft=false"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    publish(args.tag, args.assets)
