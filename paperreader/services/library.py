import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from platformdirs import user_data_dir
from paperreader.services.titles import paper_title, is_placeholder
from paperreader.services.sessions import ensure_sessions


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
            columns = {column[1] for column in self.db.execute("PRAGMA table_info(paper_index)")}
            if "favorite_rank" not in columns:
                self.db.execute("ALTER TABLE paper_index ADD COLUMN favorite_rank INTEGER NOT NULL DEFAULT 0")
            if "group_id" not in columns:
                self.db.execute("ALTER TABLE paper_index ADD COLUMN group_id INTEGER")
            self.db.execute("CREATE TABLE IF NOT EXISTS paper_groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE)")
            group_columns = {column[1] for column in self.db.execute("PRAGMA table_info(paper_groups)")}
            if "pinned_rank" not in group_columns:
                self.db.execute("ALTER TABLE paper_groups ADD COLUMN pinned_rank INTEGER NOT NULL DEFAULT 0")
            if "sort_order" not in group_columns:
                self.db.execute("ALTER TABLE paper_groups ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
                old_order = [row[0] for row in self.db.execute(
                    "SELECT id FROM paper_groups ORDER BY pinned_rank DESC, id")]
                self.db.executemany("UPDATE paper_groups SET sort_order=? WHERE id=?",
                                    ((position, group_id) for position, group_id in enumerate(old_order, 1)))

    def list_metadata(self):
        return [dict(id=row[0], title=row[1], source=row[2], favorite=bool(row[3]), group_id=row[4]) for row in
                self.db.execute("SELECT id,title,source,favorite_rank,group_id FROM paper_index WHERE removed=0 ORDER BY favorite_rank DESC, rowid DESC")]

    def list_groups(self):
        return [dict(id=row[0], name=row[1], pinned=bool(row[2])) for row in
                self.db.execute("SELECT id,name,pinned_rank FROM paper_groups ORDER BY sort_order, id")]

    def create_group(self, name):
        name = " ".join(name.split())
        if not name:
            raise ValueError("分组名称不能为空。")
        if len(name) > 50:
            raise ValueError("分组名称不能超过 50 个字符。")
        try:
            with self.db:
                cursor = self.db.execute("INSERT INTO paper_groups(name,sort_order) VALUES (?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM paper_groups))", (name,))
        except sqlite3.IntegrityError as exc:
            raise ValueError("分组名称已存在。") from exc
        return cursor.lastrowid

    def set_group(self, identifier, group_id):
        self.set_groups([identifier], group_id)

    def set_groups(self, identifiers, group_id):
        if group_id is not None and not self.db.execute("SELECT 1 FROM paper_groups WHERE id=?", (group_id,)).fetchone():
            raise ValueError("分组不存在。")
        identifiers = list(dict.fromkeys(identifiers))
        with self.db:
            for identifier in identifiers:
                cursor = self.db.execute("UPDATE paper_index SET group_id=? WHERE id=? AND removed=0", (group_id, identifier))
                if cursor.rowcount != 1:
                    raise ValueError("论文已不在列表中，未移动任何论文。")

    def rename_group(self, group_id, name):
        name = " ".join(name.split())
        if not name:
            raise ValueError("分组名称不能为空。")
        if len(name) > 50:
            raise ValueError("分组名称不能超过 50 个字符。")
        try:
            with self.db:
                cursor = self.db.execute("UPDATE paper_groups SET name=? WHERE id=?", (name, group_id))
        except sqlite3.IntegrityError as exc:
            raise ValueError("分组名称已存在。") from exc
        if not cursor.rowcount:
            raise ValueError("分组不存在。")

    def set_group_pinned(self, group_id, pinned):
        groups = self.list_groups()
        moving = next((group for group in groups if group["id"] == group_id), None)
        if moving is None:
            raise ValueError("分组不存在。")
        if moving["pinned"] == bool(pinned):
            return
        groups.remove(moving)
        moving["pinned"] = bool(pinned)
        if pinned:
            groups.insert(0, moving)
        else:
            index = next((i for i, group in enumerate(groups) if not group["pinned"]), len(groups))
            groups.insert(index, moving)
        self._save_group_order(groups)

    def reorder_group(self, group_id, target_id, after=False):
        groups = self.list_groups()
        moving = next((group for group in groups if group["id"] == group_id), None)
        target = next((group for group in groups if group["id"] == target_id), None)
        if moving is None or target is None:
            raise ValueError("分组不存在。")
        if group_id == target_id:
            return
        pinned_count = sum(group["pinned"] for group in groups)
        groups.remove(moving)
        target_index = groups.index(target) + int(after)
        groups.insert(target_index, moving)
        if moving["pinned"] and target_index >= pinned_count:
            moving["pinned"] = False
        elif not moving["pinned"] and target_index < pinned_count:
            moving["pinned"] = True
        self._save_group_order(groups)

    def _save_group_order(self, groups):
        with self.db:
            self.db.executemany("UPDATE paper_groups SET sort_order=?, pinned_rank=? WHERE id=?",
                                ((position, int(group["pinned"]), group["id"])
                                 for position, group in enumerate(groups, 1)))

    def paper_ids_in_group(self, group_id):
        return [row[0] for row in self.db.execute("SELECT id FROM paper_index WHERE group_id=?", (group_id,))]

    def delete_group(self, group_id, permanent=False):
        if not self.db.execute("SELECT 1 FROM paper_groups WHERE id=?", (group_id,)).fetchone():
            raise ValueError("分组不存在。")
        identifiers = self.paper_ids_in_group(group_id)
        if not permanent:
            with self.db:
                self.db.execute("UPDATE paper_index SET group_id=NULL WHERE group_id=?", (group_id,))
                self.db.execute("DELETE FROM paper_groups WHERE id=?", (group_id,))
            return identifiers

        staged = []
        try:
            for identifier in identifiers:
                target = self.root / "papers" / (identifier + ".pdf")
                if target.exists():
                    pending = target.with_name(f"{identifier}.{uuid.uuid4().hex}.deleting")
                    target.replace(pending)
                    staged.append((target, pending))
            with self.db:
                self.db.executemany("DELETE FROM papers WHERE id=?", ((id_,) for id_ in identifiers))
                self.db.execute("DELETE FROM paper_index WHERE group_id=?", (group_id,))
                self.db.execute("DELETE FROM paper_groups WHERE id=?", (group_id,))
        except Exception:
            for target, pending in reversed(staged):
                if pending.exists(): pending.replace(target)
            raise
        for _, pending in staged:
            pending.unlink()
        return identifiers

    def set_favorite(self, identifier, favorite):
        with self.db:
            self.db.execute("""
                UPDATE paper_index
                SET favorite_rank = CASE WHEN ? THEN
                    COALESCE((SELECT MAX(favorite_rank) FROM paper_index), 0) + 1
                    ELSE 0 END
                WHERE id = ? AND removed = 0
            """, (favorite, identifier))

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

    def clear_learning(self, paper):
        updated = dict(paper, summary="", analyses={}, notes="", messages=[], sessions=[], page=0, marks=[])
        ensure_sessions(updated)
        self.save(updated)
        return updated

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
