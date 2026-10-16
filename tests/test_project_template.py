"""The example.py that rag-kit-dev puts into new projects runs against the real API."""

import importlib.util
from pathlib import Path

import pytest

from rag_kit.pipeline import Pipeline
from rag_kit.settings import PROJECT_MARKER
from tests.conftest import ROOT, make_text_file

EXAMPLE = ROOT / "generator" / "templates" / "default" / "example.py"

pytestmark = pytest.mark.skipif(not EXAMPLE.exists(), reason="generator templates not present")


@pytest.fixture
def example(tmp_path, monkeypatch, fake_embeddings, memory_client, fake_llm):
    """The template module, run inside a fresh project with fakes behind Pipeline."""
    project = tmp_path / "my-rag"
    project.mkdir()
    (project / PROJECT_MARKER).write_text("", encoding="utf-8")
    monkeypatch.chdir(project)

    spec = importlib.util.spec_from_file_location("project_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    created = []

    def pipeline_with_fakes(settings):
        created.append(settings)
        return Pipeline(settings=settings, embeddings=fake_embeddings, client=memory_client,
                        llm=fake_llm)

    monkeypatch.setattr(module, "Pipeline", pipeline_with_fakes)
    module.created = created
    module.project = project
    return module


def test_without_arguments_it_prints_usage(example, capsys):
    assert example.main(["example.py"]) == 2
    assert "python example.py data/your-document.pdf" in capsys.readouterr().out


def test_ingests_and_answers_with_sources(example, capsys):
    data = example.project / "data"
    data.mkdir()
    doc = make_text_file(data, "notes.txt", paragraphs=10)

    assert example.main(["example.py", str(doc), "What is a noun?"]) == 0

    out = capsys.readouterr().out
    assert "Nouns name things." in out                 # answer with markers stripped
    assert "[S1] notes.txt" in out and "(score " in out
    assert example.created[0].project_dir == example.project.resolve()  # found via rag-kit.toml


def test_errors_are_reported_not_raised(example, capsys):
    assert example.main(["example.py", "missing.pdf", "q"]) == 1
    assert "error: File not found" in capsys.readouterr().err


def test_template_uses_only_the_public_api():
    source = EXAMPLE.read_text(encoding="utf-8")
    imports = {line.strip() for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert imports == {
        "import sys",
        "from rag_kit import Pipeline, Settings",
        "from rag_kit.env import export_env_file",
        "from rag_kit.errors import RagError",
        "from rag_kit.log import show_progress",
    }
    assert Path(EXAMPLE).read_bytes().count(b"GOOGLE_API_KEY=") == 0  # no key handling in code
