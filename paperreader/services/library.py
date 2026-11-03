import hashlib
import json
import sqlite3
from pathlib import Path
from platformdirs import user_data_dir


class Library:
    def __init__(self, root=None):
        self.root = Path(root or user_data_dir("PaperReader", appauthor=False))
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "papers").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.db.commit()

    def all(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM papers ORDER BY rowid DESC")]

    def save(self, paper):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO papers VALUES (?, ?)",
                            (paper["id"], json.dumps(paper, ensure_ascii=False)))

    def import_pdf(self, data, title, source=""):
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or not len(doc):
                raise ValueError("PDF 已加密或没有页面。")
        identifier = hashlib.sha256(data).hexdigest()
        for paper in self.all():
            if paper["id"] == identifier:
                return paper
        target = self.root / "papers" / (identifier + ".pdf")
        temp = target.with_suffix(".tmp")
        temp.write_bytes(data)
        temp.replace(target)
        paper = dict(id=identifier, title=title, source=source, summary="", notes="",
                     messages=[], marks=[], page=0)
        self.save(paper)
        return paper

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
