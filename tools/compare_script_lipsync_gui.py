"""ADVDATA/SCRIPT 와 LIPSYNC 번역 템플릿 대조 GUI (Tkinter).

LIPSYNC 의 각 줄마다 SCRIPT 전체에서 가장 비슷한 번역문을 찾아서
나란히 보여주고, 양쪽을 직접 고치거나 한쪽 번역으로 다른 쪽을 덮어쓸 수 있다.
original_files/ 가 없어도 동작하도록 번역문(한글) 자체를 기준으로 퍼지 매칭한다.

사용법: python tools/compare_script_lipsync_gui.py
"""
import os
import re
import difflib
import threading
import queue
from collections import Counter, defaultdict
import tkinter as tk
from tkinter import ttk, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
SCRIPT_DIR = os.path.join(BASE, 'translation_templates', 'ADVDATA', 'SCRIPT')
LIPSYNC_DIR = os.path.join(BASE, 'translation_templates', 'LIPSYNC')

LINE_RE = re.compile(r'^\[(\d+)\] ?(.*)$')
STRIP_RE = re.compile(r'//|[\s.,!?…‥・、。！？「」『』（）()\[\]~～\-—―:：;；\'"“”‘’♪★☆◆♥]+')

SIM_THRESHOLD = 0.6
CANDIDATE_MIN = 0.3
STATUSES = ['全部', '一致', '標點差異', '相似', '無對應', '空白']
STATUS_COLORS = {
    '一致': '#e6f4e6',
    '標點差異': '#fff6d5',
    '相似': '#ffe3cc',
    '無對應': '#f8d7da',
    '空白': '#eeeeee',
}


def normalize(s):
    return STRIP_RE.sub('', s)


def grams(key):
    if len(key) < 2:
        return {key}
    return {key[i:i + 2] for i in range(len(key) - 1)}


def is_control(text):
    return text.startswith('_') or text.startswith('◆')


def to_display(text):
    return text.replace('//', '\n')


def from_display(text):
    return text.replace('\r', '').replace('\n', '//')


class TemplateFile:
    def __init__(self, path):
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        with open(path, 'rb') as f:
            raw = f.read()
        self.bom = raw.startswith(b'\xef\xbb\xbf')
        self.lines = raw.decode('utf-8-sig').splitlines(keepends=True)
        self.texts = {}
        self.lineno = {}
        self.idxstr = {}
        for ln, line in enumerate(self.lines):
            m = LINE_RE.match(line.rstrip('\r\n'))
            if m:
                idx = int(m.group(1))
                self.texts[idx] = m.group(2)
                self.lineno[idx] = ln
                self.idxstr[idx] = m.group(1)
        self.dirty = False

    def set(self, idx, text):
        if self.texts.get(idx) == text:
            return False
        ln = self.lineno[idx]
        line = self.lines[ln]
        eol = line[len(line.rstrip('\r\n')):]
        self.lines[ln] = f'[{self.idxstr[idx]}] {text}{eol}'
        self.texts[idx] = text
        self.dirty = True
        return True

    def save(self):
        data = ''.join(self.lines).encode('utf-8')
        if self.bom:
            data = b'\xef\xbb\xbf' + data
        with open(self.path, 'wb') as f:
            f.write(data)
        self.dirty = False


def load_dir(path):
    if not os.path.isdir(path):
        return []
    return [TemplateFile(os.path.join(path, n))
            for n in sorted(os.listdir(path)) if n.lower().endswith('.txt')]


class Matcher:
    """SCRIPT 전체 줄에 대한 바이그램 역색인 + difflib 재정렬."""

    def __init__(self, files):
        self.entries = [(f, idx) for f in files for idx in sorted(f.texts)]
        self.norm = [''] * len(self.entries)
        self.gram_sets = [set()] * len(self.entries)
        self.exact = defaultdict(set)
        self.postings = defaultdict(set)
        for n in range(len(self.entries)):
            self._index(n)

    def _index(self, n):
        f, idx = self.entries[n]
        raw = f.texts[idx]
        key = '' if is_control(raw) else normalize(raw)
        self.norm[n] = key
        if not key:
            self.gram_sets[n] = set()
            return
        gs = grams(key)
        self.gram_sets[n] = gs
        self.exact[key].add(n)
        for g in gs:
            self.postings[g].add(n)

    def reindex(self, f, idx):
        n = self.entries.index((f, idx))
        old = self.norm[n]
        if old:
            self.exact[old].discard(n)
            for g in self.gram_sets[n]:
                self.postings[g].discard(n)
        self._index(n)

    def search(self, text, limit=20, pool=40, min_score=CANDIDATE_MIN):
        key = normalize(text)
        if not key:
            return []
        gs = grams(key)
        cnt = Counter()
        for g in gs:
            p = self.postings.get(g)
            if p:
                cnt.update(p)
        cands = set(self.exact.get(key, ()))
        if cnt:
            top = cnt.most_common(pool * 5)
            top.sort(key=lambda t: -2 * t[1] / (len(gs) + len(self.gram_sets[t[0]])))
            cands.update(n for n, _ in top[:pool])
        stripped = text.strip()
        results = []
        for n in cands:
            other = self.norm[n]
            if other == key:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, key, other, autojunk=False).ratio()
            if score >= min_score:
                f, idx = self.entries[n]
                raw_diff = f.texts[idx].strip() != stripped
                results.append((score, raw_diff, n))
        results.sort(key=lambda r: (-r[0], r[1]))
        return [(s, n) for s, _, n in results[:limit]]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry('1500x900')
        self.font = ('Malgun Gothic', 10)
        self.big_font = ('Malgun Gothic', 12)
        style = ttk.Style(self)
        style.configure('Treeview', font=self.font, rowheight=22)

        self.script_files = load_dir(SCRIPT_DIR)
        self.lip_files = load_dir(LIPSYNC_DIR)
        if not self.script_files or not self.lip_files:
            messagebox.showerror('錯誤', f'找不到範本檔案:\n{SCRIPT_DIR}\n{LIPSYNC_DIR}')
            self.destroy()
            return
        self.matcher = Matcher(self.script_files)
        self.lip_rows = [(f, idx) for f in self.lip_files for idx in sorted(f.texts)]
        self.row_by_id = {self._rid(r): r for r in self.lip_rows}
        self.best = {}
        self.candidates = []
        self.cur_lip = None
        self.cur_script = None
        self.results = queue.Queue()
        self.worker_gen = 0

        self._build_ui()
        self._update_title()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.bind_all('<Control-s>', lambda e: self.save_all())
        self.refresh_tree()
        self.start_matching()

    @staticmethod
    def _rid(row):
        f, idx = row
        return f'{f.name}:{idx}'

    # ---------- UI ----------
    def _build_ui(self):
        bar = ttk.Frame(self, padding=4)
        bar.pack(fill='x')
        ttk.Label(bar, text='LIPSYNC 檔案').pack(side='left')
        self.file_var = tk.StringVar(value='全部')
        cb = ttk.Combobox(bar, textvariable=self.file_var, state='readonly', width=12,
                          values=['全部'] + [f.name for f in self.lip_files])
        cb.pack(side='left', padx=4)
        cb.bind('<<ComboboxSelected>>', lambda e: self.refresh_tree())
        ttk.Label(bar, text='狀態').pack(side='left', padx=(10, 0))
        self.status_var = tk.StringVar(value='全部')
        cb = ttk.Combobox(bar, textvariable=self.status_var, state='readonly', width=10,
                          values=STATUSES)
        cb.pack(side='left', padx=4)
        cb.bind('<<ComboboxSelected>>', lambda e: self.refresh_tree())
        ttk.Label(bar, text='搜尋').pack(side='left', padx=(10, 0))
        self.search_var = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.search_var, width=30, font=self.font)
        ent.pack(side='left', padx=4)
        ent.bind('<Return>', lambda e: self.refresh_tree())
        ttk.Button(bar, text='篩選', command=self.refresh_tree).pack(side='left')
        ttk.Button(bar, text='重新比對全部', command=self.start_matching).pack(side='left', padx=10)
        ttk.Button(bar, text='儲存全部 (Ctrl+S)', command=self.save_all).pack(side='left')
        self.progress_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.progress_var).pack(side='right')

        paned = ttk.PanedWindow(self, orient='horizontal')
        paned.pack(fill='both', expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        cols = ('file', 'idx', 'status', 'score', 'text')
        self.tree = ttk.Treeview(left, columns=cols, show='headings', selectmode='browse')
        for c, t, w in zip(cols, ('檔案', '編號', '狀態', '分數', 'LIPSYNC 文本'),
                           (80, 50, 70, 50, 420)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=(c == 'text'))
        for st, color in STATUS_COLORS.items():
            self.tree.tag_configure(st, background=color)
        sb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.on_lip_select)
        self.count_var = tk.StringVar()
        ttk.Label(left, textvariable=self.count_var).place(relx=0, rely=1, anchor='sw')

        right = ttk.Frame(paned, padding=4)
        paned.add(right, weight=1)

        self.lip_label = tk.StringVar(value='LIPSYNC')
        ttk.Label(right, textvariable=self.lip_label, font=('Malgun Gothic', 10, 'bold')).pack(anchor='w')
        self.lip_text = tk.Text(right, height=4, font=self.big_font, wrap='word', undo=True)
        self.lip_text.pack(fill='x')
        self.lip_text.bind('<Control-Return>', lambda e: (self.apply_lip(), 'break')[1])
        self.lip_text.bind('<KeyRelease>', lambda e: self.show_diff())
        row = ttk.Frame(right)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='套用到 LIPSYNC (Ctrl+Enter)', command=self.apply_lip).pack(side='left')
        ttk.Button(row, text='用 LIPSYNC 重新搜尋', command=self.research).pack(side='left', padx=4)

        ttk.Label(right, text='SCRIPT 候選 (雙擊 = 用 SCRIPT 覆蓋 LIPSYNC)').pack(anchor='w', pady=(6, 0))
        cand_frame = ttk.Frame(right)
        cand_frame.pack(fill='both', expand=True)
        cols = ('file', 'idx', 'score', 'text')
        self.cand = ttk.Treeview(cand_frame, columns=cols, show='headings', selectmode='browse', height=8)
        for c, t, w in zip(cols, ('檔案', '編號', '分數', 'SCRIPT 文本'), (70, 50, 50, 500)):
            self.cand.heading(c, text=t)
            self.cand.column(c, width=w, stretch=(c == 'text'))
        sb = ttk.Scrollbar(cand_frame, orient='vertical', command=self.cand.yview)
        self.cand.configure(yscrollcommand=sb.set)
        self.cand.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.cand.bind('<<TreeviewSelect>>', self.on_cand_select)
        self.cand.bind('<Double-1>', lambda e: self.copy_script_to_lip())

        self.script_label = tk.StringVar(value='SCRIPT')
        ttk.Label(right, textvariable=self.script_label, font=('Malgun Gothic', 10, 'bold')).pack(anchor='w', pady=(6, 0))
        self.script_text = tk.Text(right, height=4, font=self.big_font, wrap='word', undo=True)
        self.script_text.pack(fill='x')
        self.script_text.bind('<Control-Return>', lambda e: (self.apply_script(), 'break')[1])
        self.script_text.bind('<KeyRelease>', lambda e: self.show_diff())
        row = ttk.Frame(right)
        row.pack(fill='x', pady=2)
        ttk.Button(row, text='套用到 SCRIPT (Ctrl+Enter)', command=self.apply_script).pack(side='left')
        ttk.Button(row, text='↑ 用 SCRIPT 覆蓋 LIPSYNC', command=self.copy_script_to_lip).pack(side='left', padx=4)
        ttk.Button(row, text='↓ 用 LIPSYNC 覆蓋 SCRIPT', command=self.copy_lip_to_script).pack(side='left')

        ttk.Label(right, text='差異 (紅 = 只在 LIPSYNC, 綠 = 只在 SCRIPT)').pack(anchor='w', pady=(6, 0))
        self.diff_text = tk.Text(right, height=4, font=self.big_font, wrap='word', state='disabled',
                                 background='#fafafa')
        self.diff_text.pack(fill='x')
        self.diff_text.tag_configure('del', background='#f8b4b4')
        self.diff_text.tag_configure('ins', background='#b4f0b4')
        self.diff_text.tag_configure('head', foreground='#666666')

        ttk.Label(right, text='SCRIPT 前後文').pack(anchor='w', pady=(6, 0))
        self.ctx_text = tk.Text(right, height=7, font=self.font, wrap='none', state='disabled',
                                background='#fafafa')
        self.ctx_text.pack(fill='x')
        self.ctx_text.tag_configure('cur', background='#dde8ff')

    # ---------- matching ----------
    def start_matching(self):
        self.worker_gen += 1
        gen = self.worker_gen
        rows = list(self.lip_rows)
        texts = [f.texts[idx] for f, idx in rows]
        self.progress_var.set('比對中…')

        def work():
            for i, (row, text) in enumerate(zip(rows, texts)):
                if gen != self.worker_gen:
                    return
                res = self.matcher.search(text, limit=1, pool=30, min_score=0.0)
                self.results.put((gen, row, res[0] if res else None, i + 1, len(rows)))
            self.results.put((gen, None, None, len(rows), len(rows)))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self.poll_results)

    def poll_results(self):
        done = False
        changed = []
        try:
            while True:
                gen, row, best, i, total = self.results.get_nowait()
                if gen != self.worker_gen:
                    continue
                if row is None:
                    done = True
                    break
                self.best[row] = best
                changed.append(row)
                self.progress_var.set(f'比對中… {i}/{total}')
        except queue.Empty:
            pass
        for row in changed:
            self.update_row(row)
        if done:
            self.progress_var.set(self.summary())
            if self.status_var.get() != '全部':
                self.refresh_tree()
        else:
            self.after(150, self.poll_results)

    def summary(self):
        c = Counter(self.classify(r)[0] for r in self.lip_rows)
        return '  '.join(f'{s}:{c.get(s, 0)}' for s in STATUSES[1:])

    def classify(self, row):
        f, idx = row
        text = f.texts[idx]
        if not normalize(text):
            return '空白', None
        if row not in self.best:
            return '…', None
        best = self.best[row]
        if best is None or best[0] < SIM_THRESHOLD:
            return '無對應', best[0] if best else None
        score, n = best
        if score >= 1.0:
            sf, si = self.matcher.entries[n]
            return ('一致' if sf.texts[si].strip() == text.strip() else '標點差異'), score
        return '相似', score

    def row_values(self, row):
        f, idx = row
        status, score = self.classify(row)
        return (f.name, idx, status, '' if score is None else f'{score:.2f}', f.texts[idx]), status

    def update_row(self, row):
        rid = self._rid(row)
        if self.tree.exists(rid):
            values, status = self.row_values(row)
            self.tree.item(rid, values=values, tags=(status,))

    def refresh_tree(self):
        fname = self.file_var.get()
        status = self.status_var.get()
        q = self.search_var.get().strip()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for row in self.lip_rows:
            f, idx = row
            if fname != '全部' and f.name != fname:
                continue
            values, st = self.row_values(row)
            if status != '全部' and st != status:
                continue
            if q and q not in f.texts[idx]:
                continue
            self.tree.insert('', 'end', iid=self._rid(row), values=values, tags=(st,))
            shown += 1
        self.count_var.set(f'{shown} 行')
        if self.cur_lip and self.tree.exists(self._rid(self.cur_lip)):
            self.tree.see(self._rid(self.cur_lip))

    # ---------- selection ----------
    def on_lip_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.row_by_id[sel[0]]
        self.cur_lip = row
        f, idx = row
        self.lip_label.set(f'LIPSYNC  {f.name} [{idx:04d}]')
        self.set_text(self.lip_text, to_display(f.texts[idx]))
        self.load_candidates(f.texts[idx])

    def research(self):
        if self.cur_lip:
            self.load_candidates(from_display(self.lip_text.get('1.0', 'end-1c')))

    def load_candidates(self, text):
        self.cand.delete(*self.cand.get_children())
        self.candidates = self.matcher.search(text)
        for i, (score, n) in enumerate(self.candidates):
            f, idx = self.matcher.entries[n]
            self.cand.insert('', 'end', iid=str(i), values=(f.name, idx, f'{score:.2f}', f.texts[idx]))
        if self.candidates:
            self.cand.selection_set('0')
        else:
            self.cur_script = None
            self.script_label.set('SCRIPT  (沒有候選)')
            self.set_text(self.script_text, '')
            self.show_context()
            self.show_diff()

    def on_cand_select(self, _event=None):
        sel = self.cand.selection()
        if not sel:
            return
        _, n = self.candidates[int(sel[0])]
        f, idx = self.matcher.entries[n]
        self.cur_script = (f, idx)
        self.script_label.set(f'SCRIPT  {f.name} [{idx:04d}]')
        self.set_text(self.script_text, to_display(f.texts[idx]))
        self.show_context()
        self.show_diff()

    @staticmethod
    def set_text(widget, text):
        state = widget.cget('state')
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.edit_reset()
        widget.configure(state=state)

    def show_context(self):
        w = self.ctx_text
        w.configure(state='normal')
        w.delete('1.0', 'end')
        if self.cur_script:
            f, idx = self.cur_script
            for i in range(idx - 3, idx + 4):
                if i in f.texts:
                    tag = ('cur',) if i == idx else ()
                    w.insert('end', f'[{i:04d}] {f.texts[i]}\n', tag)
        w.configure(state='disabled')

    def show_diff(self):
        a = from_display(self.lip_text.get('1.0', 'end-1c')) if self.cur_lip else ''
        b = from_display(self.script_text.get('1.0', 'end-1c')) if self.cur_script else ''
        w = self.diff_text
        w.configure(state='normal')
        w.delete('1.0', 'end')
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        w.insert('end', 'LIPSYNC: ', 'head')
        for op, i1, i2, _, _ in sm.get_opcodes():
            w.insert('end', a[i1:i2], () if op == 'equal' else ('del',))
        w.insert('end', '\nSCRIPT:  ', 'head')
        for op, _, _, j1, j2 in sm.get_opcodes():
            w.insert('end', b[j1:j2], () if op == 'equal' else ('ins',))
        w.configure(state='disabled')

    # ---------- editing ----------
    def apply_lip(self, text=None):
        if not self.cur_lip:
            return
        f, idx = self.cur_lip
        if text is None:
            text = from_display(self.lip_text.get('1.0', 'end-1c'))
        else:
            self.set_text(self.lip_text, to_display(text))
        if f.set(idx, text):
            self.best[self.cur_lip] = (self.matcher.search(text, limit=1, min_score=0.0) or [None])[0]
            self.update_row(self.cur_lip)
            self._update_title()
        self.show_diff()

    def apply_script(self, text=None):
        if not self.cur_script:
            return
        f, idx = self.cur_script
        if text is None:
            text = from_display(self.script_text.get('1.0', 'end-1c'))
        else:
            self.set_text(self.script_text, to_display(text))
        if f.set(idx, text):
            self.matcher.reindex(f, idx)
            sel = self.cand.selection()
            if sel:
                vals = list(self.cand.item(sel[0], 'values'))
                vals[3] = text
                self.cand.item(sel[0], values=vals)
            if self.cur_lip:
                lf, li = self.cur_lip
                self.best[self.cur_lip] = (self.matcher.search(lf.texts[li], limit=1, min_score=0.0) or [None])[0]
                self.update_row(self.cur_lip)
            self.show_context()
            self._update_title()
        self.show_diff()

    def copy_script_to_lip(self):
        if self.cur_script and self.cur_lip:
            self.apply_lip(from_display(self.script_text.get('1.0', 'end-1c')))

    def copy_lip_to_script(self):
        if self.cur_script and self.cur_lip:
            self.apply_script(from_display(self.lip_text.get('1.0', 'end-1c')))

    # ---------- saving ----------
    def dirty_files(self):
        return [f for f in self.script_files + self.lip_files if f.dirty]

    def _update_title(self):
        n = len(self.dirty_files())
        self.title(f'SCRIPT ↔ LIPSYNC 對照工具' + (f'  * 未儲存 {n} 個檔案' if n else ''))

    def save_all(self):
        files = self.dirty_files()
        for f in files:
            f.save()
        self._update_title()
        self.progress_var.set(f'已儲存 {len(files)} 個檔案' if files else '沒有需要儲存的變更')

    def on_close(self):
        if self.dirty_files():
            ans = messagebox.askyesnocancel('未儲存', '有未儲存的變更，要先儲存嗎？')
            if ans is None:
                return
            if ans:
                self.save_all()
        self.worker_gen += 1
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
