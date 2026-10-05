"""번체 중국어 번역 청크 검증.

사용법: python tools/cht_check.py p1_000 [p1_001 ...]   (인자 없으면 전체)
cht_work/chunks/<name>.tsv 와 cht_work/out/<name>.tsv 를 비교해 문제를 출력한다.
종료 코드: 오류가 있으면 1.
"""
import os, re, sys, glob, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(BASE, 'cht_work')

KEEP_CHARS = '∈〓「」『』（）◆▼→⌒¬⊇∋⊆∩√∽θκνξ≪≫‰'
CODE_RE = re.compile(r'%[a-z]*\d+|@[a-z]+[\d,]*|\\t')
KANA_RE = re.compile(r'[\u3041-\u3096\u30a1-\u30fa]')
JP_ONLY_RE = re.compile(r'[\u3040-\u30ff]')
MAX_SEG = 16


def read_tsv(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            line = line.rstrip('\r\n')
            if not line.strip():
                continue
            parts = line.split('\t')
            rows.append((ln, parts))
    return rows


def width(s):
    return sum(0.5 if unicodedata.east_asian_width(c) in ('Na', 'H') else 1 for c in s)


def lead_spaces(seg):
    return len(seg) - len(seg.lstrip('\u3000'))


def check_pair(src, dst):
    errs, warns = [], []
    if not dst.strip():
        errs.append('譯文是空的')
        return errs, warns
    if src.count('//') != dst.count('//'):
        errs.append(f'// 數量不同 (原文 {src.count("//")}, 譯文 {dst.count("//")})')
    for ch in KEEP_CHARS:
        a, b = src.count(ch), dst.count(ch)
        if a != b:
            errs.append(f'「{ch}」數量不同 (原文 {a}, 譯文 {b})')
    if sorted(CODE_RE.findall(src)) != sorted(CODE_RE.findall(dst)):
        errs.append(f'控制碼不同 原文 {CODE_RE.findall(src)} 譯文 {CODE_RE.findall(dst)}')
    if KANA_RE.search(dst):
        errs.append('譯文殘留平假名/片假名')
    ss, ds = src.split('//'), dst.split('//')
    if len(ss) == len(ds):
        for i, (a, b) in enumerate(zip(ss, ds)):
            if lead_spaces(a) != lead_spaces(b):
                errs.append(f'第 {i + 1} 段行首全形空格數不同 (原文 {lead_spaces(a)}, 譯文 {lead_spaces(b)})')
    if JP_ONLY_RE.search(src):
        for i, seg in enumerate(ds):
            w = width(seg)
            if w > MAX_SEG:
                warns.append(f'第 {i + 1} 段 {w:g} 字，超過 {MAX_SEG}')
    if '！' in dst.replace('∈', '') and '！' not in src and '!' not in src and '∈' in src:
        warns.append('原文用 ∈，譯文出現「！」')
    return errs, warns


def check_chunk(name):
    src_path = os.path.join(WORK, 'chunks', name + '.tsv')
    out_path = os.path.join(WORK, 'out', name + '.tsv')
    if not os.path.exists(out_path):
        return [f'{name}: 找不到輸出檔 {out_path}'], []
    src = read_tsv(src_path)
    out = read_tsv(out_path)
    errs, warns = [], []
    out_map = {}
    for ln, parts in out:
        if len(parts) != 2:
            errs.append(f'{name} 輸出第 {ln} 行: 欄位數 {len(parts)}，應為 2 (ID<TAB>譯文)')
            continue
        uid, text = parts
        if uid in out_map:
            errs.append(f'{name} {uid}: ID 重複')
        out_map[uid] = text
    src_ids = [p[0] for _, p in src]
    extra = set(out_map) - set(src_ids)
    if extra:
        errs.append(f'{name}: 多出的 ID {sorted(extra)[:10]}')
    for _, parts in src:
        uid, text = parts[0], parts[1]
        if uid not in out_map:
            errs.append(f'{uid}: 缺少譯文')
            continue
        e, w = check_pair(text, out_map[uid])
        errs += [f'{uid}: {m}' for m in e]
        warns += [f'{uid}: {m}' for m in w]
    return errs, warns


def main():
    names = sys.argv[1:] or sorted(os.path.splitext(os.path.basename(p))[0]
                                   for p in glob.glob(os.path.join(WORK, 'chunks', '*.tsv')))
    total_e = total_w = 0
    for name in names:
        errs, warns = check_chunk(name)
        total_e += len(errs)
        total_w += len(warns)
        for m in errs:
            print('錯誤', m)
        for m in warns:
            print('警告', m)
        print(f'== {name}: 錯誤 {len(errs)}，警告 {len(warns)}')
    sys.exit(1 if total_e else 0)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
