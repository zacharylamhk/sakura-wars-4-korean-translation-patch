"""SLG 일본어를 SCRIPT/LIPSYNC 번체 사전과 맞춰 남은 줄만 청크로 나눈다.

  python tools/cht_prepare_slg.py

출력:
  cht_work/slg_alias.json   SLG 원문 -> 이미 있는 번체(정확/문장부호만 다름)
  cht_work/slg_units.json   새로 번역할 uid
  cht_work/chunks/p3_XXX.tsv
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare_script_lipsync_gui as cg

BASE = cg.BASE
WORK = os.path.join(BASE, 'cht_work')
CHUNK_DIR = os.path.join(WORK, 'chunks')
SLG_DIR = os.path.join(BASE, 'translation_templates', 'SLG')
JP = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]')
LINE = re.compile(r'^\[(\d+)\] ?(.*)$')
CHUNK_CHARS = 6500
NEAR = 0.8


def load_file(path):
    d = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = LINE.match(line.rstrip('\n'))
            if m:
                d[int(m.group(1))] = m.group(2)
    return d


def walk_txt(root):
    out = []
    for dp, _, fn in os.walk(root):
        for n in sorted(fn):
            if n.endswith('.txt'):
                out.append(os.path.join(dp, n))
    return out


def known_dict():
    known, by_src, files = {}, {}, []
    pairs = [
        (os.path.join(BASE, 'translation_templates', 'ADVDATA', 'SCRIPT'),
         os.path.join(BASE, 'translation_templates_cht', 'ADVDATA', 'SCRIPT')),
        (os.path.join(BASE, 'translation_templates', 'LIPSYNC'),
         os.path.join(BASE, 'translation_templates_cht', 'LIPSYNC')),
    ]
    for srcd, chtd in pairs:
        for p in walk_txt(srcd):
            rel = os.path.relpath(p, srcd)
            cp = os.path.join(chtd, rel)
            if not os.path.exists(cp):
                continue
            a, b = load_file(p), load_file(cp)
            tf = cg.TemplateFile(p)
            files.append(tf)
            for i, t in a.items():
                if not JP.search(t) or i not in b:
                    continue
                by_src[t] = b[i]
                known[t] = b[i]
    return known, files


def esc(s):
    return s.replace('\t', '\\t')


def write_chunks(prefix, items):
    chunks, cur, size = [], [], 0
    for item in items:
        cur.append(item)
        size += len(item[1])
        if size >= CHUNK_CHARS:
            chunks.append(cur)
            cur, size = [], 0
    if cur:
        chunks.append(cur)
    for n, ch in enumerate(chunks):
        with open(os.path.join(CHUNK_DIR, f'{prefix}_{n:03d}.tsv'), 'w', encoding='utf-8') as f:
            for row in ch:
                f.write('\t'.join(esc(str(c)) for c in row) + '\n')
    return len(chunks)


def main():
    os.makedirs(CHUNK_DIR, exist_ok=True)
    known, src_files = known_dict()
    norm_known = {}
    for t, cht in known.items():
        norm_known.setdefault(cg.normalize(t), (t, cht))
    matcher = cg.Matcher(src_files)

    alias, units, p3, seen = {}, {}, [], set()
    for p in walk_txt(SLG_DIR):
        for t in load_file(p).values():
            if not JP.search(t) or t in seen:
                continue
            seen.add(t)
            if t in known:
                alias[t] = known[t]
                continue
            key = cg.normalize(t)
            if key in norm_known:
                alias[t] = norm_known[key][1]
                continue
            ref_jp = ref_cht = None
            res = matcher.search(t, limit=1, pool=30, min_score=0.0)
            if res and res[0][0] >= NEAR:
                sf, si = matcher.entries[res[0][1]]
                ref_jp = sf.texts[si]
                ref_cht = known.get(ref_jp)
            uid = f'G{len(p3):05d}'
            units[uid] = {'src': t, 'kind': 'slg', 'ref': ref_jp}
            row = (uid, t)
            if ref_jp and ref_cht:
                row = (uid, t, ref_jp, ref_cht)
            p3.append(row)

    with open(os.path.join(WORK, 'slg_alias.json'), 'w', encoding='utf-8') as f:
        json.dump(alias, f, ensure_ascii=False, indent=0)
    with open(os.path.join(WORK, 'slg_units.json'), 'w', encoding='utf-8') as f:
        json.dump(units, f, ensure_ascii=False, indent=0)
    n = write_chunks('p3', p3)
    print(f'SLG unique JP {len(seen)}; reuse SCRIPT/LIPSYNC {len(alias)}; '
          f'new {len(p3)} -> {n} chunks; near-ref {sum(1 for r in p3 if len(r) > 2)}')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
