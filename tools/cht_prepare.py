"""SCRIPT + LIPSYNC 일본어 원문을 중복 제거해서 번체 중국어 번역용 작업 청크로 나눈다.

출력 (cht_work/):
  units.json        uid -> {src, kind('script'|'lip'), ref(근접 SCRIPT uid 또는 null)}
  lip_alias.json    LIPSYNC 원문 -> 그대로 재사용할 SCRIPT uid (정확히/문장부호만 다른 경우)
  chunks/p1_XXX.tsv SCRIPT 순서대로 (uid<TAB>원문)
  chunks/p2_XXX.tsv LIPSYNC 전용 줄 (uid<TAB>원문[<TAB>참고 SCRIPT uid])

사용법: python tools/cht_prepare.py
"""
import os, sys, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare_script_lipsync_gui as cg

BASE = cg.BASE
WORK = os.path.join(BASE, 'cht_work')
CHUNK_DIR = os.path.join(WORK, 'chunks')
JP = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]')
CHUNK_CHARS = 6500
NEAR = 0.8


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
    script = cg.load_dir(cg.SCRIPT_DIR)
    lip = cg.load_dir(cg.LIPSYNC_DIR)

    units, by_src, p1 = {}, {}, []
    for f in script:
        for idx in sorted(f.texts):
            t = f.texts[idx]
            if not JP.search(t) or t in by_src:
                continue
            uid = f'S{len(units):05d}'
            units[uid] = {'src': t, 'kind': 'script', 'ref': None}
            by_src[t] = uid
            p1.append((uid, t))

    norm_to_uid = {}
    for t, uid in by_src.items():
        norm_to_uid.setdefault(cg.normalize(t), uid)

    matcher = cg.Matcher(script)
    alias, lip_seen, p2 = {}, set(), []
    for f in lip:
        for idx in sorted(f.texts):
            t = f.texts[idx]
            if not JP.search(t) or t in alias or t in lip_seen:
                continue
            if t in by_src:
                alias[t] = by_src[t]
                continue
            key = cg.normalize(t)
            if key in norm_to_uid:
                alias[t] = norm_to_uid[key]
                continue
            lip_seen.add(t)
            res = matcher.search(t, limit=1, pool=30, min_score=0.0)
            ref = None
            if res and res[0][0] >= NEAR:
                sf, si = matcher.entries[res[0][1]]
                ref = by_src.get(sf.texts[si])
            uid = f'L{len(p2):05d}'
            units[uid] = {'src': t, 'kind': 'lip', 'ref': ref}
            p2.append((uid, t) + ((ref,) if ref else ()))

    with open(os.path.join(WORK, 'units.json'), 'w', encoding='utf-8') as f:
        json.dump(units, f, ensure_ascii=False, indent=0)
    with open(os.path.join(WORK, 'lip_alias.json'), 'w', encoding='utf-8') as f:
        json.dump(alias, f, ensure_ascii=False, indent=0)
    n1 = write_chunks('p1', p1)
    n2 = write_chunks('p2', p2)
    print(f'SCRIPT units {len(p1)} -> {n1} chunks; LIPSYNC-only {len(p2)} -> {n2} chunks; '
          f'LIPSYNC reusing SCRIPT {len(alias)}; with near ref {sum(1 for r in p2 if len(r) > 2)}')


if __name__ == '__main__':
    main()
