"""
Format-aware extraction pipeline for Field Work artifacts.

Supports: .docx, .xlsx, .pdf, .pptx, .md, .txt
Normalized output schema:
    {
        artifact_id: str,
        extracted_at: str (ISO),
        source_format: str,
        title_extracted: str | None,
        sections: [{heading, level, content}],
        tables: [{section_index, rows}],
        full_text: str,
        word_count: int,
        extraction_notes: [str],
    }
"""

import re
from datetime import datetime
from pathlib import Path
from .logging import get_logger

_log = get_logger(__name__)


def extract_artifact(artifact_id: str, original_path: Path, file_extension: str) -> dict:
    """
    Dispatch to the correct format extractor and return the normalized schema.
    Saves nothing — caller is responsible for persisting the result.
    """
    ext = file_extension.lower().lstrip(".")
    dispatch = {
        "docx": _extract_docx,
        "xlsx": _extract_xlsx,
        "pdf":  _extract_pdf,
        "pptx": _extract_pptx,
        "md":   _extract_markdown,
        "txt":  _extract_txt,
    }

    _log.info("field_extract_start", artifact_id=artifact_id, ext=ext, path=str(original_path))

    extractor = dispatch.get(ext)
    if extractor is None:
        raise ValueError(f"Unsupported file format: {ext!r}")

    result = extractor(original_path)
    result["artifact_id"] = artifact_id
    result["extracted_at"] = datetime.now().isoformat()
    result["source_format"] = ext
    result["full_text"] = _build_full_text(result["sections"])
    result["word_count"] = len(result["full_text"].split())

    _log.info(
        "field_extract_complete",
        artifact_id=artifact_id,
        ext=ext,
        sections=len(result["sections"]),
        word_count=result["word_count"],
        notes=len(result["extraction_notes"]),
    )
    return result


# ── Format extractors ────────────────────────────────────────────────────────

def _extract_docx(path: Path) -> dict:
    from docx import Document
    from docx.oxml.ns import qn

    sections = []
    tables = []
    notes = []
    title_extracted = None

    try:
        doc = Document(str(path))
    except Exception as exc:
        notes.append(f"Failed to open docx: {exc}")
        return _empty(notes)

    current_section_idx = 0

    for elem in doc.element.body:
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "p":
            try:
                from docx.text.paragraph import Paragraph
                para = Paragraph(elem, doc)
                text = para.text.strip()
                if not text:
                    continue
                style_name = para.style.name if para.style else ""
                level = _heading_level_from_style(style_name)
                if level is not None:
                    if level == 1 and title_extracted is None:
                        title_extracted = text
                    sections.append({"heading": text, "level": level, "content": ""})
                    current_section_idx = len(sections) - 1
                else:
                    if sections:
                        sep = "\n" if sections[-1]["content"] else ""
                        sections[-1]["content"] += sep + text
                    else:
                        sections.append({"heading": "", "level": 0, "content": text})
                        current_section_idx = 0
            except Exception as exc:
                notes.append(f"Paragraph parse error: {exc}")

        elif tag == "tbl":
            try:
                from docx.table import Table
                tbl = Table(elem, doc)
                rows = []
                for row in tbl.rows:
                    rows.append([cell.text.strip() for cell in row.cells])
                tables.append({"section_index": current_section_idx, "rows": rows})
            except Exception as exc:
                notes.append(f"Table parse error: {exc}")

    return {
        "title_extracted": title_extracted,
        "sections": sections,
        "tables": tables,
        "extraction_notes": notes,
    }


def _extract_xlsx(path: Path) -> dict:
    import openpyxl

    sections = []
    tables = []
    notes = []
    title_extracted = None

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        notes.append(f"Failed to open xlsx: {exc}")
        return _empty(notes)

    for sheet_idx, sheet_name in enumerate(wb.sheetnames):
        try:
            ws = wb[sheet_name]
            if sheet_idx == 0:
                title_extracted = sheet_name

            rows = []
            for row in ws.iter_rows(values_only=True):
                str_row = [str(cell) if cell is not None else "" for cell in row]
                if any(c.strip() for c in str_row):
                    rows.append(str_row)

            content_lines = ["\t".join(r) for r in rows]
            sections.append({
                "heading": sheet_name,
                "level": 1,
                "content": "\n".join(content_lines),
            })
            tables.append({"section_index": len(sections) - 1, "rows": rows})
        except Exception as exc:
            notes.append(f"Sheet {sheet_name!r} parse error: {exc}")

    wb.close()
    return {
        "title_extracted": title_extracted,
        "sections": sections,
        "tables": tables,
        "extraction_notes": notes,
    }


def _extract_pdf(path: Path) -> dict:
    import pdfplumber

    sections = []
    notes = []
    title_extracted = None

    try:
        pdf = pdfplumber.open(str(path))
    except Exception as exc:
        notes.append(f"Failed to open pdf: {exc}")
        return _empty(notes)

    try:
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
                text = text.strip()
                if page_num == 1 and text:
                    first_line = text.splitlines()[0].strip()
                    if first_line:
                        title_extracted = first_line
                sections.append({
                    "heading": f"Page {page_num}",
                    "level": 1,
                    "content": text,
                })
            except Exception as exc:
                notes.append(f"Page {page_num} parse error: {exc}")
    finally:
        pdf.close()

    return {
        "title_extracted": title_extracted,
        "sections": sections,
        "tables": [],
        "extraction_notes": notes,
    }


def _extract_pptx(path: Path) -> dict:
    from pptx import Presentation
    from pptx.util import Pt

    sections = []
    notes = []
    title_extracted = None

    try:
        prs = Presentation(str(path))
    except Exception as exc:
        notes.append(f"Failed to open pptx: {exc}")
        return _empty(notes)

    for slide_idx, slide in enumerate(prs.slides, start=1):
        try:
            slide_title = None
            content_parts = []

            for shape in slide.shapes:
                try:
                    if not shape.has_text_frame:
                        continue
                    text = shape.text_frame.text.strip()
                    if not text:
                        continue
                    # First text box on first slide with content = title
                    if slide_title is None:
                        slide_title = text
                        if slide_idx == 1:
                            title_extracted = text
                    else:
                        content_parts.append(text)
                except Exception as exc:
                    notes.append(f"Slide {slide_idx} shape error: {exc}")

            sections.append({
                "heading": slide_title or f"Slide {slide_idx}",
                "level": 1,
                "content": "\n".join(content_parts),
            })
        except Exception as exc:
            notes.append(f"Slide {slide_idx} parse error: {exc}")

    return {
        "title_extracted": title_extracted,
        "sections": sections,
        "tables": [],
        "extraction_notes": notes,
    }


def _extract_markdown(path: Path) -> dict:
    sections = []
    notes = []
    title_extracted = None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        notes.append(f"Failed to read file: {exc}")
        return _empty(notes)

    current_heading = ""
    current_level = 0
    current_lines = []

    def flush():
        if current_heading or current_lines:
            sections.append({
                "heading": current_heading,
                "level": current_level,
                "content": "\n".join(current_lines).strip(),
            })

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush()
            current_level = len(m.group(1))
            current_heading = m.group(2).strip()
            current_lines = []
            if current_level == 1 and title_extracted is None:
                title_extracted = current_heading
        else:
            current_lines.append(line)

    flush()

    if not sections:
        sections.append({"heading": "", "level": 0, "content": text.strip()})

    return {
        "title_extracted": title_extracted,
        "sections": sections,
        "tables": [],
        "extraction_notes": notes,
    }


def _extract_txt(path: Path) -> dict:
    notes = []
    title_extracted = None

    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        notes.append(f"Failed to read file: {exc}")
        return _empty(notes)

    first_line = text.splitlines()[0].strip() if text else ""
    if first_line:
        title_extracted = first_line[:120]

    return {
        "title_extracted": title_extracted,
        "sections": [{"heading": "", "level": 0, "content": text}],
        "tables": [],
        "extraction_notes": notes,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _heading_level_from_style(style_name: str) -> int | None:
    """Return heading level (1–6) from a Word style name, or None if not a heading."""
    m = re.match(r"[Hh]eading\s+(\d)", style_name)
    if m:
        return int(m.group(1))
    return None


def _build_full_text(sections: list[dict]) -> str:
    parts = []
    for s in sections:
        if s.get("heading"):
            parts.append(s["heading"])
        if s.get("content"):
            parts.append(s["content"])
    return "\n\n".join(parts)


def _empty(notes: list) -> dict:
    return {
        "title_extracted": None,
        "sections": [],
        "tables": [],
        "extraction_notes": notes,
    }
