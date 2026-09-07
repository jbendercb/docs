#!/usr/bin/env python3
"""Sync the published Agent Skills into .mintlify/skills/ so docs.corestory.ai
serves them at /.well-known/agent-skills/<slug>/SKILL.md.

CoreStoryAI/agent-skills is the single source of truth for skill content. This
script only copies; it never edits a skill. Run with --check in CI to fail when
the docs tree has drifted from the published release.

  python3 scripts/sync-skills.py            # write .mintlify/skills/
  python3 scripts/sync-skills.py --check    # exit 1 if out of sync
  python3 scripts/sync-skills.py --ref v1.0.0
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "CoreStoryAI/agent-skills"
DOCS = Path(__file__).resolve().parents[1]
DEST = DOCS / ".mintlify" / "skills"
SKILLS_SUBPATH = "plugins/corestory/skills"
FM = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def fetch_skills(ref: str) -> dict[str, bytes]:
    url = f"https://codeload.github.com/{REPO}/zip/refs/heads/{ref}"
    if re.fullmatch(r"v?\d+\.\d+\.\d+", ref):
        url = f"https://codeload.github.com/{REPO}/zip/refs/tags/{ref}"
    with urllib.request.urlopen(url, timeout=60) as r:
        blob = r.read()
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if len(parts) < 5 or info.is_dir():
                continue
            # <repo>-<ref>/plugins/corestory/skills/<name>/SKILL.md
            rest = "/".join(parts[1:])
            if not rest.startswith(SKILLS_SUBPATH + "/") or not rest.endswith("/SKILL.md"):
                continue
            name = rest[len(SKILLS_SUBPATH) + 1 : -len("/SKILL.md")]
            if "/" in name:
                continue
            out[name] = z.read(info)
    if not out:
        raise SystemExit(f"no skills found in {REPO}@{ref} under {SKILLS_SUBPATH}/")
    return out


def validate(name: str, raw: bytes) -> str:
    text = raw.decode("utf-8")
    m = FM.match(text)
    if not m:
        raise SystemExit(f"{name}: missing YAML frontmatter")
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, val = line.partition(":")
        if sep:
            fields[key.strip()] = val.strip().strip('"')
    for required in ("name", "description", "license"):
        if not fields.get(required):
            raise SystemExit(f"{name}: frontmatter is missing {required!r}, which Mintlify requires")
    if fields["name"] != name:
        raise SystemExit(f"{name}: frontmatter name {fields['name']!r} does not match its directory")
    if not SLUG.fullmatch(name):
        raise SystemExit(f"{name}: not a URL-safe slug, so its served path would be unstable")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="main", help="branch or tag of the skills repo (default: main)")
    ap.add_argument("--check", action="store_true", help="verify only; do not write")
    args = ap.parse_args()

    skills = fetch_skills(args.ref)
    wanted = {name: validate(name, raw) for name, raw in sorted(skills.items())}

    have = {p.parent.name: p.read_text(encoding="utf-8") for p in DEST.glob("*/SKILL.md")}
    added = sorted(set(wanted) - set(have))
    removed = sorted(set(have) - set(wanted))
    modified = sorted(n for n in set(wanted) & set(have) if wanted[n] != have[n])

    if args.check:
        if added or removed or modified:
            print(f".mintlify/skills/ is out of sync with {REPO}@{args.ref}:")
            for n in added:
                print(f"  + {n}")
            for n in removed:
                print(f"  - {n}")
            for n in modified:
                print(f"  ~ {n}")
            print("\nRun: python3 scripts/sync-skills.py")
            return 1
        print(f".mintlify/skills/ is in sync with {REPO}@{args.ref} ({len(wanted)} skills)")
        return 0

    if DEST.exists():
        shutil.rmtree(DEST)
    for name, text in wanted.items():
        d = DEST / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(text, encoding="utf-8")
    (DEST / ".synced.json").write_text(
        json.dumps({"source": REPO, "ref": args.ref, "skills": sorted(wanted)}, indent=2) + "\n",
        encoding="utf-8",
    )
    verb = "unchanged"
    if added or removed or modified:
        verb = f"+{len(added)} -{len(removed)} ~{len(modified)}"
    print(f"synced {len(wanted)} skills from {REPO}@{args.ref} into .mintlify/skills/ ({verb})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
