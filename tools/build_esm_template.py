"""ESM 파일들에서 실제 대사만 골라 번역 템플릿 생성 (위치정보도 같이 저장)"""
from extract_esm_text import scan_esm
import os, json

def is_real_text(t):
    return bool(t) and any(ord(c) >= 0x3000 for c in t)

def build_template(esm_path, out_txt_path, out_manifest_path):
    chunks = scan_esm(esm_path)
    lines_out = []
    manifest = []  # [{idx, pos, byte_len}]
    idx = 0
    for c in chunks:
        for li, t in enumerate(c['texts']):
            if not is_real_text(t):
                continue
            pos, blen = c['positions'][li]
            lines_out.append(f"[{idx:04d}] {t}")
            manifest.append({'idx': idx, 'pos': pos, 'byte_len': blen})
            idx += 1

    os.makedirs(os.path.dirname(out_txt_path), exist_ok=True)
    with open(out_txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines_out) + '\n')
    with open(out_manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f)
    return idx

if __name__ == '__main__':
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(base, 'esm_templates')
    total = 0
    for n in range(1, 6):
        esm = os.path.join(base, 'original_files', 'SLG', f'G0{n}', f'SMAP0{n}.ESM')
        out = os.path.join(out_dir, f'SMAP0{n}.txt')
        manifest = os.path.join(out_dir, f'SMAP0{n}.manifest.json')
        count = build_template(esm, out, manifest)
        print(f"SMAP0{n}.ESM: 實際對白 {count} 行 -> {out}")
        total += count
    print("合計:", total)
