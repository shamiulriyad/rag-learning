"""Optional PDF font repair (rag/pdf_font_repair.py)."""

import pytest

from rag.pdf_font_repair import (BODY_FONT, BODY_MAP, BOLD_FONT, BOLD_MAP, is_readable,
                                 repair_page)
from tests.conftest import ROOT

GRAMMAR_PDF = ROOT / "-Free-English-Grammar.pdf"


def _encode(text, fmap):
    reverse = {}
    for code, char in fmap.items():
        reverse.setdefault(char, code)
    return "".join(chr(reverse[c]) for c in text)


class FakePage:
    """Mimics pymupdf's page.get_text('rawdict') for a list of (font, raw) spans."""

    def __init__(self, *lines):
        self.lines = lines

    def get_text(self, mode):
        assert mode == "rawdict"
        return {"blocks": [{"lines": [
            {"spans": [{"font": font, "chars": [{"c": ch} for ch in raw]} for font, raw in line]}
            for line in self.lines
        ]}]}


def test_decodes_body_and_bold_fonts_and_passes_others_through():
    page = FakePage(
        [(BOLD_FONT, _encode("nouns", BOLD_MAP))],
        [(BODY_FONT, _encode("Countable nouns can be plural.", BODY_MAP)),
         ("Times-Roman", " 185")],
    )
    assert repair_page(page) == "nouns\nCountable nouns can be plural. 185"


def test_swallows_phantom_glyph_after_capitals():
    # The broken font draws "H" as <H><0x20>; 0x20 alone would decode to "v".
    raw = chr(0x2C) + chr(0x20) + _encode("ello", BODY_MAP)
    assert repair_page(FakePage([(BODY_FONT, raw)])) == "Hello"


def test_drops_unmapped_control_glyphs():
    raw = _encode("ab", BODY_MAP) + "\x12" + _encode("c", BODY_MAP)
    assert repair_page(FakePage([(BODY_FONT, raw)])) == "abc"


def test_readability_score():
    assert is_readable("Countable nouns are nouns which can form a plural.")
    assert not is_readable("& ? ! & & ? ! & & ? ! # # %")


@pytest.mark.skipif(not GRAMMAR_PDF.exists(), reason="tracked grammar PDF not present")
def test_repairs_a_real_page_of_the_grammar_pdf():
    import pymupdf

    with pymupdf.open(str(GRAMMAR_PDF)) as doc:
        page = doc[184]  # printed page 185, "Countable nouns"
        plain = page.get_text("text")
        repaired = repair_page(page)

    assert not is_readable(plain)
    assert is_readable(repaired)
    assert "Countable nouns are nouns which can form a plural" in repaired
