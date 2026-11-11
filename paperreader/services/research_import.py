"""Read local knowledge files into searchable text."""
from itertools import chain
from pathlib import Path

DOCUMENT_LIMIT = 32 * 1024 * 1024
TEXT_LIMIT = 2_000_000


def read_knowledge_file(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if path.stat().st_size > DOCUMENT_LIMIT:
        raise ValueError("文件超过 32 MB")
    if suffix == ".pdf":
        return path.read_bytes()
    if suffix == ".docx":
        from docx import Document

        document = Document(path)
        lines = (paragraph.text for paragraph in document.paragraphs)
        tables = ("\t".join(cell.text for cell in row.cells)
                  for table in document.tables for row in table.rows)
        return collect_text(chain(lines, tables))
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True, data_only=True)
        try:
            return collect_text(sheet_lines((sheet.title, sheet.values) for sheet in book))
        finally:
            book.close()
    if suffix == ".xls":
        from xlrd import open_workbook

        with open_workbook(path, on_demand=True) as book:
            return collect_text(sheet_lines(
                (sheet.name, (sheet.row_values(index) for index in range(sheet.nrows)))
                for sheet in book.sheets()))
    if suffix in (".txt", ".md", ".markdown", ".json", ".rst", ".csv", ".tsv", ".log"):
        with path.open("rb") as source:
            data = source.read(TEXT_LIMIT + 1)
        if len(data) > TEXT_LIMIT:
            raise ValueError("文本超过 2 MB")
        return collect_text([data.decode("utf-8-sig")])
    raise ValueError("不支持的文件格式")


def sheet_lines(sheets):
    for title, rows in sheets:
        yield f"工作表：{title}"
        for row in rows:
            if any(value is not None and value != "" for value in row):
                yield "\t".join("" if value is None else str(value) for value in row).rstrip("\t")


def collect_text(lines):
    parts = []
    size = 0
    for line in lines:
        if not line.strip():
            continue
        size += len(line.encode("utf-8")) + 1
        if size > TEXT_LIMIT:
            raise ValueError("提取后的文本超过 2 MB")
        parts.append(line)
    text = "\n".join(parts)
    if not text or "\x00" in text:
        raise ValueError("没有可检索的文本")
    return text
