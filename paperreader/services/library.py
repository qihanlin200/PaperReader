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
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_index'").fetchone()
        with self.db:
            if not exists: self.db.execute("BEGIN")
            self.db.execute("CREATE TABLE IF NOT EXISTS paper_index (id TEXT PRIMARY KEY, title TEXT, source TEXT, removed INTEGER NOT NULL DEFAULT 0)")
            if not exists:
                self.db.execute("INSERT INTO paper_index SELECT id, json_extract(data, '$.title'), COALESCE(json_extract(data, '$.source'), ''), COALESCE(json_extract(data, '$.removed'), 0) FROM papers ORDER BY rowid")

    def list_metadata(self):
        return [dict(id=row[0], title=row[1], source=row[2]) for row in
                self.db.execute("SELECT id,title,source FROM paper_index WHERE removed=0 ORDER BY rowid DESC")]

    def get(self, identifier):
        row = self.db.execute("SELECT data FROM papers WHERE id=?", (identifier,)).fetchone()
        if row is None: raise ValueError("论文记录不存在。")
        paper = json.loads(row[0])
        if is_placeholder(paper['title']):
            try:
                import fitz
                with fitz.open(self.pdf_path(paper)) as doc:
                    paper['title'] = paper_title(doc, paper['title'])
                self.save(paper)
            except (OSError, ValueError): pass
        return paper

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
            self.db.execute("INSERT INTO paper_index(id,title,source,removed) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,source=excluded.source,removed=excluded.removed",
                            (paper['id'], paper['title'], paper.get('source',''), int(paper.get('removed',False))))

    def import_pdf(self, data, title, source=""):
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or not len(doc):
                raise ValueError("PDF 已加密或没有页面。")
            title = paper_title(doc, title)
        identifier = hashlib.sha256(data).hexdigest()
        if self.db.execute("SELECT 1 FROM papers WHERE id=?", (identifier,)).fetchone():
            paper = self.get(identifier)
            if paper.get('removed'):
                paper['removed'] = False; self.save(paper)
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
        paper = self.get(paper["id"])
        if not permanent:
            retained = dict(paper); retained["removed"] = True
            self.save(retained); return
        target = self.pdf_path(paper)
        pending = target.with_suffix('.deleting')
        if target.exists(): target.replace(pending)
        try:
            with self.db:
                self.db.execute("DELETE FROM papers WHERE id=?", (paper["id"],))
                self.db.execute("DELETE FROM paper_index WHERE id=?", (paper["id"],))
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
