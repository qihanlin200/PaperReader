import hashlib
import json
import sqlite3
from pathlib import Path
from platformdirs import user_data_dir
from paperreader.services.titles import paper_title, is_placeholder


class Library:
    def __init__(self, root=None):
        self.root = Path(root or user_data_dir("PaperReader", appauthor=False))
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "papers").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite3")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.commit()

    def all(self, include_removed=False):
        papers = [json.loads(row[0]) for row in self.db.execute("SELECT data FROM papers ORDER BY rowid DESC")]
        for paper in papers:
            if is_placeholder(paper["title"]):
                try:
                    import fitz
                    with fitz.open(self.pdf_path(paper)) as doc:
                        paper["title"] = paper_title(doc, paper["title"])
                    self.save(paper)
                except (OSError, ValueError): pass
        return papers if include_removed else [p for p in papers if not p.get("removed", False)]

    def save(self, paper):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO papers VALUES (?, ?)",
                            (paper["id"], json.dumps(paper, ensure_ascii=False)))

    def import_pdf(self, data, title, source=""):
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or not len(doc):
                raise ValueError("PDF 已加密或没有页面。")
            title = paper_title(doc, title)
        identifier = hashlib.sha256(data).hexdigest()
        for paper in self.all(include_removed=True):
            if paper["id"] == identifier:
                if paper.get("removed"):
                    paper["removed"] = False; self.save(paper)
                return paper
        target = self.root / "papers" / (identifier + ".pdf")
        temp = target.with_suffix(".tmp")
        temp.write_bytes(data)
        temp.replace(target)
        paper = dict(id=identifier, title=title, source=source, summary="", notes="",
                     messages=[], marks=[], page=0)
        self.save(paper)
        return paper

    def remove(self, paper, permanent=False):
        if not permanent:
            retained = dict(paper); retained["removed"] = True
            self.save(retained); return
        target = self.pdf_path(paper)
        pending = target.with_suffix('.deleting')
        if target.exists(): target.replace(pending)
        try:
            with self.db:
                self.db.execute("DELETE FROM papers WHERE id=?", (paper["id"],))
                if pending.exists(): pending.unlink()
        except Exception:
            if pending.exists(): pending.replace(target)
            raise

    def pdf_path(self, paper):
        return self.root / "papers" / (paper["id"] + ".pdf")

    def config(self):
        path = self.root / "config.json"
        return json.loads(path.read_text()) if path.exists() else {"endpoint": "https://api.openai.com/v1", "model": ""}

    def save_config(self, config):
        path = self.root / "config.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(config), encoding="utf-8")
        temp.replace(path)
