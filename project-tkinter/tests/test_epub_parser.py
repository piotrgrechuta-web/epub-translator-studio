from __future__ import annotations

import io
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from translation_engine import (  # noqa: E402
    XHTML_NS,
    _xpath_translatable,
    find_opf_path,
    has_translatable_text,
    inner_xml,
    normalize_epub_path,
    parse_batch_response,
    parse_spine_and_manifest,
    replace_inner_xml,
)


def _container_xml(opf_ref: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_ref}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


@contextmanager
def _epub_with_opf(
    opf_xml: str,
    *,
    opf_disk_path: str = "OPS/content.opf",
    opf_ref_in_container: str | None = None,
):
    buf = io.BytesIO()
    opf_ref = opf_ref_in_container or opf_disk_path
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", _container_xml(opf_ref))
        zf.writestr(opf_disk_path, opf_xml)
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        yield zf


def test_find_opf_path_normalizes_backslashes() -> None:
    opf = "<package><manifest/><spine/></package>"
    with _epub_with_opf(opf, opf_disk_path="OPS/content.opf", opf_ref_in_container="OPS\\content.opf") as zf:
        assert find_opf_path(zf) == "OPS/content.opf"


def test_parse_spine_and_manifest_reads_expected_items() -> None:
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="chap1" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="css" href="Styles/book.css" media-type="text/css"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
"""
    with _epub_with_opf(opf) as zf:
        manifest, spine = parse_spine_and_manifest(zf, "OPS/content.opf")
    assert spine == ["chap1"]
    assert manifest["chap1"] == ("Text/chapter1.xhtml", "application/xhtml+xml")
    assert manifest["css"] == ("Styles/book.css", "text/css")


def test_parse_spine_and_manifest_requires_non_empty_manifest_and_spine() -> None:
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="chap1" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine/>
</package>
"""
    with _epub_with_opf(opf) as zf:
        with pytest.raises(ValueError, match="manifest/spine"):
            parse_spine_and_manifest(zf, "OPS/content.opf")


def test_normalize_epub_path_removes_fragment_and_backslashes() -> None:
    out = normalize_epub_path("OPS/content.opf", "Text\\chapter1.xhtml#frag")
    assert out == "OPS/Text/chapter1.xhtml"


def test_inline_tags_round_trip_parse_and_replace() -> None:
    raw_response = (
        "Translation:\n"
        "```xml\n"
        f"<batch xmlns=\"{XHTML_NS}\"><seg id=\"s1\">Ala <b>ma</b> <i>kota</i>.</seg></batch>\n"
        "```"
    )
    mapping = parse_batch_response(raw_response)
    assert mapping["s1"] == "Ala <b>ma</b> <i>kota</i>."

    p = etree.fromstring(f"<p xmlns=\"{XHTML_NS}\">Old text</p>".encode("utf-8"))
    replace_inner_xml(p, mapping["s1"])
    assert inner_xml(p) == "Ala <b>ma</b> <i>kota</i>."


def test_xpath_translatable_skips_script_and_style_ancestors() -> None:
    raw = f"""<html xmlns="{XHTML_NS}">
  <body>
    <p>Ala <b>ma</b> kota</p>
    <script><p>Do not translate</p></script>
    <style><p>Do not translate</p></style>
  </body>
</html>"""
    root = etree.fromstring(raw.encode("utf-8"))
    elements = root.xpath(_xpath_translatable(("p",)))

    assert len(elements) == 1
    assert has_translatable_text(elements[0]) is True
    assert "Ala" in inner_xml(elements[0])
