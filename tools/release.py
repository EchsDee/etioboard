"""Empacota dist/etioboard e (opcionalmente) publica a release no GitHub.

Uso:
    python tools/release.py              # só gera dist/etioboard-<versão>-win64.zip (+ .sha256)
    python tools/release.py --publish    # gera e cria a release v<versão> com `gh`

As notas da release vêm de --notes "texto" ou --notes-file arquivo.md. O app instalado
encontra a release pelo nome do zip e confere o SHA-256 antes de instalar.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.paths import APP_NAME, APP_VERSION  # noqa: E402


def build_zip(build_dir: Path, out: Path) -> str:
    if not (build_dir / f"{APP_NAME}.exe").exists():
        sys.exit(f"Build não encontrado em {build_dir}. Rode build.bat antes.")
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(build_dir.rglob("*")):
            if path.is_file():
                zf.write(path, Path(APP_NAME) / path.relative_to(build_dir))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_name(out.name + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="ascii")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="cria a release no GitHub com gh")
    parser.add_argument("--notes", default="", help="notas da versão")
    parser.add_argument("--notes-file", help="arquivo com as notas da versão")
    args = parser.parse_args()

    dist = ROOT / "dist"
    zip_path = dist / f"{APP_NAME}-{APP_VERSION}-win64.zip"
    digest = build_zip(dist / APP_NAME, zip_path)
    size_mb = zip_path.stat().st_size / 1e6
    print(f"Pacote: {zip_path} ({size_mb:.0f} MB)\nSHA-256: {digest}")

    if args.publish:
        tag = f"v{APP_VERSION}"
        cmd = ["gh", "release", "create", tag, str(zip_path), str(zip_path) + ".sha256",
               "--title", f"{APP_NAME} {APP_VERSION}"]
        cmd += ["--notes-file", args.notes_file] if args.notes_file else ["--notes", args.notes or f"Versão {APP_VERSION}"]
        print("Publicando", tag, "...")
        subprocess.run(cmd, check=True, cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
