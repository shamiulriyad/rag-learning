"""End-to-end test of the rag-kit-dev generator.

    python scripts/ci/e2e_generator.py --generator rag-kit-dev-0.1.0.tgz \
        --wheel rag_kit-0.1.0-py3-none-any.whl --work <empty dir> \
        [--source wheel|testpypi|pypi] [--python PATH] \
        [--cases gemini-uv,gemini-pip,no-install,failure,refusals,local]

--generator is the packed tarball (CI, release rehearsal) or an npm spec such
as rag-kit-dev@0.1.0 (after publishing). --source says where the generated
project gets rag-kit: the local --wheel (--package-spec), TestPyPI
(--test-pypi), or PyPI (no option, as a user would). In every mode the
installed rag-kit must be exactly the files of --wheel, so a release check
proves the package came from the build under test.

Everything runs in a scrubbed environment: no rag-kit settings or API keys,
HF_HOME inside --work and HF_HUB_OFFLINE=1, so nothing can download a model.
No case ingests or asks. Exits 1 on the first failed expectation.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ALL_CASES = ["gemini-uv", "gemini-pip", "no-install", "failure", "refusals", "local"]
DEFAULT_CASES = [case for case in ALL_CASES if case != "local"]
PROJECT_FILES = [
    ".env.example",
    ".gitignore",
    "README.md",
    "data/.gitkeep",
    "example.py",
    "rag-kit.toml",
    "requirements.txt",
]
SCRUBBED = (
    "RAG_PROJECT_DIR",
    "RAG_ENV_FILE",
    "RAG_EXPORT_ENV",
    "RAG_API_WARMUP",
    "QDRANT_PATH",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "COLLECTION_NAME",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "PYTHONPATH",
    "VIRTUAL_ENV",
)
HERE = Path(__file__).resolve().parent


class Failed(Exception):
    pass


def expect(condition, message, output=""):
    if not condition:
        raise Failed(
            message + (f"\n--- output (last 2000 chars) ---\n{output[-2000:]}" if output else "")
        )
    print(f"  ok  {message}")


def pep440(version):
    """npm's 0.1.0-rc.1 -> 0.1.0rc1; final versions are unchanged."""
    labels = {"alpha": "a", "beta": "b", "rc": "rc"}
    return re.sub(
        r"-(alpha|beta|rc)\.?(\d+)$", lambda m: f"{labels[m.group(1)]}{m.group(2)}", version
    )


class Runner:
    def __init__(self, args):
        self.work = args.work.resolve()
        self.wheel = args.wheel.resolve()
        self.source = args.source
        self.python = args.python
        generator = Path(args.generator)
        self.generator = str(generator.resolve()) if generator.exists() else args.generator
        # rag_kit-0.1.0rc1-py3-none-any.whl -> 0.1.0rc1
        self.version = self.wheel.name.split("-")[1]
        self.hf_home = self.work / "hf-home"
        self.npx = shutil.which("npx")
        if not self.npx:
            raise Failed("npx not found on PATH")
        self.env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
        self.env.update(
            HF_HOME=str(self.hf_home),
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            PYTHONIOENCODING="utf-8",
            PYTHONDONTWRITEBYTECODE="1",
        )

    def run(self, args, cwd, env=None):
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env or self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=3600,
        )
        return result.returncode, result.stdout + result.stderr

    def generate(self, *args):
        installing = "--no-install" not in args
        extra = []
        if installing and self.python:
            extra += ["--python", self.python]
        if installing and self.source == "wheel" and "--package-spec" not in args:
            extra += ["--package-spec", str(self.wheel)]
        if installing and self.source == "testpypi":
            extra += ["--test-pypi"]
        return self.run(
            [self.npx, "--yes", f"--package={self.generator}", "rag-kit-dev", *args, *extra],
            cwd=self.work,
        )

    def tool(self, project, name):
        scripts = project / ".venv" / ("Scripts" if os.name == "nt" else "bin")
        return str(scripts / (f"{name}.exe" if os.name == "nt" else name))

    def project_files(self, project):
        return sorted(
            p.relative_to(project).as_posix()
            for p in project.rglob("*")
            if p.is_file() and ".venv" not in p.relative_to(project).parts
        )

    def check_installed_project(self, project, extras):
        name = project.name
        expect(self.project_files(project) == PROJECT_FILES, f"{name}: exactly the project files")
        expect(not (project / ".env").exists(), f"{name}: no .env")
        env_example = (project / ".env.example").read_text(encoding="utf-8")
        expect("\nGOOGLE_API_KEY=\n" in env_example, f"{name}: .env.example key is empty")
        pins = [
            line
            for line in (project / "requirements.txt").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        match = re.fullmatch(r"rag-kit\[([a-z,]+)\]==(.+)", pins[0]) if len(pins) == 1 else None
        expect(
            match is not None
            and match.group(1) == extras
            and pep440(match.group(2)) == self.version,
            f"{name}: requirements.txt pins {pins}",
        )

        code, out = self.run(
            [
                self.tool(project, "python"),
                str(HERE / "check_wheel_install.py"),
                "--wheel",
                str(self.wheel),
            ],
            cwd=project,
        )
        expect(
            code == 0,
            f"{name}: installed rag-kit is exactly {self.wheel.name} ({self.source})",
            out,
        )
        code, out = self.run([self.tool(project, "rag-kit"), "--help"], cwd=project)
        expect(code == 0, f"{name}: rag-kit --help", out)
        code, out = self.run([self.tool(project, "rag-kit"), "check"], cwd=project)
        expect(
            code == 0 and "[warn] .env" in out and "cp .env.example .env" in out,
            f"{name}: rag-kit check passes and explains .env",
            out,
        )
        code, out = self.run([self.tool(project, "python"), "example.py"], cwd=project)
        expect(code == 2 and "python example.py data/" in out, f"{name}: example.py usage", out)

        # The template's settings as they would be after `cp .env.example .env`, read
        # through RAG_ENV_FILE so that no .env file is ever created.
        settings_copy = self.work / f"{name}-settings-copy.env"
        shutil.copy(project / ".env.example", settings_copy)
        code, out = self.run(
            [self.tool(project, "rag-kit"), "check"],
            cwd=project,
            env={**self.env, "RAG_ENV_FILE": str(settings_copy)},
        )
        provider = (
            "huggingface: BAAI/bge-m3"
            if "local" in extras
            else "google: models/gemini-embedding-001"
        )
        expect(
            provider in out and "qdrant_data" in out,
            f"{name}: template settings give {provider} and a project-local store",
            out,
        )
        expect(
            not (project / ".env").exists() and not (project / "qdrant_data").exists(),
            f"{name}: still no .env and no qdrant_data",
        )

    # --- cases -------------------------------------------------------------------
    def gemini_uv(self):
        code, out = self.generate("my-rag", "--embeddings", "gemini")
        expect(code == 0 and "Installer: uv" in out, "gemini + uv: generator exit 0", out)
        self.check_installed_project(self.work / "my-rag", "gemini")

    def gemini_pip(self):
        code, out = self.generate("my-rag-pip", "--embeddings", "gemini", "--no-uv")
        expect(code == 0 and "Installer: pip" in out, "gemini + pip: generator exit 0", out)
        self.check_installed_project(self.work / "my-rag-pip", "gemini")

    def no_install(self):
        code, out = self.generate("my-rag-files", "--embeddings", "local", "--no-install")
        project = self.work / "my-rag-files"
        expect(code == 0 and "Skipped installation" in out, "--no-install: exit 0", out)
        expect(
            self.project_files(project) == PROJECT_FILES, "--no-install: exactly the project files"
        )
        expect(
            not (project / ".env").exists() and not (project / ".venv").exists(),
            "--no-install: no .env and no .venv",
        )

    def failure(self):
        missing = self.work / "missing-rag_kit-0.0.0-py3-none-any.whl"
        code, out = self.generate(
            "my-rag-fail", "--embeddings", "gemini", "--package-spec", str(missing)
        )
        project = self.work / "my-rag-fail"
        expect(code == 1, "failing install: exit 1", out)
        expect(
            "were kept" in out and "To finish" in out,
            "failing install: explains and prints retry",
            out,
        )
        expect(self.project_files(project) == PROJECT_FILES, "failing install: project files kept")

    def refusals(self):
        occupied = self.work / "occupied"
        occupied.mkdir()
        (occupied / "notes.txt").write_text("user data", encoding="utf-8")
        code, out = self.generate("occupied", "--embeddings", "gemini", "--no-install")
        expect(
            code == 2 and [p.name for p in occupied.iterdir()] == ["notes.txt"],
            "non-empty folder refused and untouched",
            out,
        )
        code, out = self.generate("needs-choice")
        expect(
            code == 2
            and "--embeddings local or --embeddings gemini" in out
            and not (self.work / "needs-choice").exists(),
            "non-interactive run without --embeddings refused, nothing created",
            out,
        )
        code, out = self.generate("../escape", "--embeddings", "gemini")
        expect(
            code == 2 and not (self.work.parent / "escape").exists(), "path-like name refused", out
        )

    def local(self):
        code, out = self.generate("my-rag-local", "--embeddings", "local")
        expect(code == 0, "local + uv: generator exit 0", out)
        project = self.work / "my-rag-local"
        self.check_installed_project(project, "local,gemini")
        code, out = self.run(
            [self.tool(project, "python"), str(HERE / "check_cpu_torch.py")], cwd=project
        )
        print("     " + out.strip().replace("\n", "\n     "))
        if sys.platform.startswith("linux"):
            expect(code == 0, "local: CPU-only PyTorch (Linux installs from the CPU index)", out)
        downloaded = (
            [p for p in self.hf_home.rglob("*") if p.is_file()] if self.hf_home.exists() else []
        )
        expect(not downloaded, "local: no model was downloaded (HF_HOME is empty)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--generator", required=True, help="packed tarball or npm spec")
    parser.add_argument("--wheel", type=Path, required=True, help="the rag-kit build under test")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--source", choices=["wheel", "testpypi", "pypi"], default="wheel")
    parser.add_argument("--python", help="interpreter passed to the generator as --python")
    parser.add_argument("--cases", default=",".join(DEFAULT_CASES))
    args = parser.parse_args(argv)

    args.work.mkdir(parents=True, exist_ok=True)
    if any(args.work.iterdir()):
        print(f"--work must be empty: {args.work}")
        return 2
    try:
        runner = Runner(args)
        for case in args.cases.split(","):
            if case not in ALL_CASES:
                raise Failed(f"unknown case {case!r}")
            print(f"\n### {case} (rag-kit from {args.source})")
            getattr(runner, case.replace("-", "_"))()
    except Failed as failure:
        print(f"FAIL {failure}")
        return 1
    print("\nAll generator end-to-end cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
