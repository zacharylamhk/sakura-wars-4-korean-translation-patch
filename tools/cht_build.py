"""번체 중국어 번역 결과를 translation_templates_cht/ 에 조립한다.

  python tools/cht_build.py refs    p2 청크에 참고 SCRIPT 원문/번역을 채운다 (p1 번역 후 실행)
  python tools/cht_build.py build   translation_templates_cht/ADVDATA/SCRIPT, LIPSYNC 생성

LIPSYNC 줄의 원문이 SCRIPT와 같으면(또는 문장부호만 다르면) SCRIPT 번역을 그대로 쓴다.
"""
import os, sys, re, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare_script_lipsync_gui as cg

BASE = cg.BASE
WORK = os.path.join(BASE, 'cht_work')
OUT_ROOT = os.path.join(BASE, 'translation_templates_cht')
JP = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]')


def load_json(name):
    with open(os.path.join(WORK, name), encoding='utf-8') as f:
        return json.load(f)


def load_translations():
    trans = {}
    for path in sorted(glob.glob(os.path.join(WORK, 'out', '*.tsv'))):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\r\n')
                if '\t' in line:
                    uid, text = line.split('\t', 1)
                    trans[uid] = text.replace('\\t', '\t')
    return trans


def cmd_refs():
    units = load_json('units.json')
    trans = load_translations()
    missing = 0
    for path in sorted(glob.glob(os.path.join(WORK, 'chunks', 'p2_*.tsv'))):
        rows = []
        with open(path, encoding='utf-8') as f:
            for line in f:
                parts = line.rstrip('\r\n').split('\t')
                uid, src = parts[0], parts[1]
                ref = units[uid]['ref']
                if ref:
                    if ref not in trans:
                        missing += 1
                        rows.append([uid, src])
                        continue
                    rows.append([uid, src, units[ref]['src'].replace('\t', '\\t'),
                                 trans[ref].replace('\t', '\\t')])
                else:
                    rows.append([uid, src])
        with open(path, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write('\t'.join(r) + '\n')
    print(f'參考譯文已填入；缺少參考譯文 {missing} 句')


def cmd_build():
    units = load_json('units.json')
    alias = load_json('lip_alias.json')
    trans = load_translations()
    src_uid = {}
    for uid, u in units.items():
        src_uid.setdefault(u['src'], uid)

    missing = []

    def translate(text, where):
        if not JP.search(text):
            return text
        uid = alias.get(text) or src_uid.get(text)
        if uid and uid in trans:
            return trans[uid]
        missing.append((where, text))
        return text

    for sub, files in (('ADVDATA/SCRIPT', cg.load_dir(cg.SCRIPT_DIR)),
                       ('LIPSYNC', cg.load_dir(cg.LIPSYNC_DIR))):
        out_dir = os.path.join(OUT_ROOT, *sub.split('/'))
        os.makedirs(out_dir, exist_ok=True)
        for f in files:
            for idx in sorted(f.texts):
                f.set(idx, translate(f.texts[idx], f'{f.name}[{idx:04d}]'))
            f.path = os.path.join(out_dir, os.path.basename(f.path))
            f.save()
            print(f'寫入 {os.path.relpath(f.path, BASE)}')

    print(f'未翻譯（保留日文）: {len(missing)} 行')
    for where, text in missing[:30]:
        print('  ', where, text)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    {'refs': cmd_refs, 'build': cmd_build}[sys.argv[1] if len(sys.argv) > 1 else 'build']()
