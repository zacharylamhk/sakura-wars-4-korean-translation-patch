"""
櫻花大戰 4 繁體中文翻譯一併套用工具。
一次執行會把已譯好的對白（SBX/SBN）+ LIPSYNC +（若有範本）1ST_READ.BIN
等寫進磁碟結構，並產生含繁體缺字的 SKFONT.CG~4.CG。

使用法（專案根目錄）:
  python translate_all_cht.py

翻譯來源是 translation_templates_cht/，路徑對應遊戲磁碟
（例如 translation_templates_cht/ADVDATA/SCRIPT/S0120.txt）。
尚未翻譯的 [編號] 行會自動維持日文原文。

目前繁中範本只有 ADVDATA/SCRIPT 與 LIPSYNC；其他區塊沒有對應檔時會跳過。

產出在 output_cht/。把該資料夾 zip 後改副檔名 .dcp，
即可交給 Universal Dreamcast Patcher 的 Apply Patch。
"""
import os, sys, argparse

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, 'tools')
sys.path.insert(0, TOOLS_DIR)

import hangul_font_map as fontmap
from rebuild_sbx import rebuild as rebuild_sbx_file
from patch_1st_read_repoint import patch as patch_1st_read_file
from patch_esm import patch as patch_esm_file
from patch_esm_ticker import patch as patch_esm_ticker_file
from patch_lipsync import patch as patch_lipsync_file
from patch_ovlm_binary import patch as patch_ovlm_file
from patch_movecatch_binary import patch as patch_movecatch_file
from hangul_font_map import load_map, patch_skfont, set_space_mode

ORIGINAL_DIR = os.path.join(BASE_DIR, 'original_files')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'translation_templates_cht')
ORIGINAL_TXT_DIR = os.path.join(BASE_DIR, 'original_txt')
ORIGINAL_1ST_READ = os.path.join(TOOLS_DIR, '1ST_READ.BIN')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output_cht')
CHT_MAP_FILE = os.path.join(TOOLS_DIR, 'cht_map.json')
ALL_STRINGS_TEMPLATE_REL = os.path.join('1ST_READ', 'all_1st_read_strings.txt')
ESM_NAMES = ['SMAP01', 'SMAP02', 'SMAP03', 'SMAP04', 'SMAP05']
ESM_GROUP = {'SMAP01': 'G01', 'SMAP02': 'G02', 'SMAP03': 'G03', 'SMAP04': 'G04', 'SMAP05': 'G05'}
LIPSYNC_NAMES = ['LIPSYNC1', 'LIPSYNC2', 'LIPSYNC3', 'LIPSYNC4']
OVLM_FILES = [('APPEND', 'ADVDATA/APPEND/APPEND.BIN'), ('MGJT', 'MINIGAME/MGJT.BIN')]
MOVECATCH_FILES = [
    ('ADVDATA/MOVE.txt', 'ADVDATA/MOVE.BIN'),
    ('ADVDATA/EYECATCH/EYECATCH.txt', 'ADVDATA/EYECATCH/EYECATCH.BIN'),
    ('ADVDATA/CINEMA/CINEMA.txt', 'ADVDATA/CINEMA/CINEMA.BIN'),
    ('ADVDATA/ENDING.txt', 'ADVDATA/ENDING.BIN'),
]


def find_cht_font():
    windir = os.environ.get('WINDIR', r'C:\Windows')
    fonts = os.path.join(windir, 'Fonts')
    for name, idx in (
        ('msjh.ttc', 0),
        ('msjhl.ttc', 0),
        ('mingliu.ttc', 0),
        ('kaiu.ttf', 0),
    ):
        path = os.path.join(fonts, name)
        if os.path.exists(path):
            return path, idx
    fallback = os.path.join(TOOLS_DIR, 'NotoSansKR-subset.ttf')
    if os.path.exists(fallback):
        print('警告: 找不到微軟正黑體/細明體，改用韓文字型，部份繁體字可能缺字')
        return fallback, 0
    raise SystemExit('找不到可用的繁體中文字型（需要 C:\\Windows\\Fonts\\msjh.ttc）')


def find_original(base_no_ext):
    for ext in ('.SBX', '.SBN'):
        p = base_no_ext + ext
        if os.path.exists(p):
            return p
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spacing', choices=['skip', 'tile'], default='skip',
                        help="空白處理。skip=不插入空白直接接上"
                             " / tile=借用空漢字格畫空白（遊戲裡可能顯示成兩格寬）")
    args = parser.parse_args()
    set_space_mode(args.spacing)

    font_path, font_index = find_cht_font()
    fontmap.set_map_file(CHT_MAP_FILE)
    fontmap.set_font_path(font_path, font_index)
    print(f"(空白處理: {args.spacing})")
    print(f"(字型: {font_path} index={font_index})")
    print(f"(字碼表: {CHT_MAP_FILE})\n")

    all_skipped = []

    print("=== 1) 對白腳本 (SBX/SBN) ===")
    sbx_files_done = 0
    total_sbx_lines = 0
    if os.path.isdir(TEMPLATES_DIR):
        for root, dirs, files in os.walk(TEMPLATES_DIR):
            rel_root = os.path.relpath(root, TEMPLATES_DIR)
            if rel_root.split(os.sep)[0] == '1ST_READ':
                continue
            for fname in sorted(files):
                if not fname.endswith('.txt'):
                    continue
                rel_path = os.path.join(rel_root, fname) if rel_root != '.' else fname
                base_no_ext = os.path.join(ORIGINAL_DIR, rel_path[:-4])
                src = find_original(base_no_ext)
                if not src:
                    continue
                template_path = os.path.join(root, fname)
                out_path = os.path.join(OUTPUT_DIR, os.path.dirname(rel_path),
                                        os.path.basename(src))
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                stats = rebuild_sbx_file(src, template_path, out_path, out_font_dir=None)
                if stats['translated_count'] > 0:
                    print(f"  {rel_path}: {stats['translated_count']}/{stats['real_total']} 行已套用")
                    sbx_files_done += 1
                    total_sbx_lines += stats['translated_count']
                else:
                    os.remove(out_path)
    if sbx_files_done == 0:
        print("  沒有已翻譯的對白（跳過）")

    print("\n=== 2) SRPG 戰鬥對白 (ESM) ===")
    esm_files_done = 0
    total_esm_lines = 0
    for esm_name in ESM_NAMES:
        template_path = os.path.join(TEMPLATES_DIR, 'SLG_ESM', esm_name + '.txt')
        src_esm = os.path.join(ORIGINAL_DIR, 'SLG_ESM', esm_name + '.ESM')
        if not (os.path.exists(template_path) and os.path.exists(src_esm)):
            continue
        out_esm = os.path.join(OUTPUT_DIR, 'SLG', ESM_GROUP[esm_name], esm_name + '.ESM')
        os.makedirs(os.path.dirname(out_esm), exist_ok=True)
        applied, total, _, _ = patch_esm_file(src_esm, template_path, out_esm, out_font_dir=None)

        ticker_orig = os.path.join(ORIGINAL_TXT_DIR, 'SLG_ESM', 'SMAP_ticker.txt')
        ticker_tpl = os.path.join(TEMPLATES_DIR, 'SLG_ESM', 'SMAP_ticker.txt')
        ticker_applied = 0
        if os.path.exists(ticker_orig) and os.path.exists(ticker_tpl) and os.path.exists(out_esm):
            ticker_applied, ticker_total, ticker_too_long, _ = patch_esm_ticker_file(
                out_esm, ticker_orig, ticker_tpl, out_esm)
            if ticker_too_long:
                print(f"    {esm_name}.ESM 狀態列超過 24 位元組而跳過: {len(ticker_too_long)} 筆")

        if applied > 0 or ticker_applied > 0:
            print(f"  {esm_name}.ESM: {applied}/{total} 句對白, 狀態列 {ticker_applied} 筆")
            esm_files_done += 1
            total_esm_lines += applied + ticker_applied
        else:
            os.remove(out_esm)
    if esm_files_done == 0:
        print("  沒有 ESM 繁中範本（跳過）")

    print("\n=== 3) 唇形同步語音對白 (LIPSYNC) ===")
    # 不回寫範本：translation_templates_cht/LIPSYNC 已與 SCRIPT 對齊。
    lip_files_done = 0
    total_lip_lines = 0
    for lip_name in LIPSYNC_NAMES:
        template_path = os.path.join(TEMPLATES_DIR, 'LIPSYNC', lip_name + '.txt')
        src_lip = os.path.join(ORIGINAL_DIR, 'ADVDATA', lip_name + '.LIP')
        if not (os.path.exists(template_path) and os.path.exists(src_lip)):
            continue
        out_lip = os.path.join(OUTPUT_DIR, 'ADVDATA', lip_name + '.LIP')
        os.makedirs(os.path.dirname(out_lip), exist_ok=True)
        applied, total, _, encode_failed, too_long = patch_lipsync_file(
            src_lip, template_path, out_lip, out_font_dir=None)
        if applied > 0:
            print(f"  {lip_name}.LIP: {applied}/{total} 句已套用（表值不變，只改 pre+text 合併空間）")
            if too_long:
                print(f"    注意: 空間不足而維持原文 {len(too_long)} 句")
                for i, orig, trans, need, have in too_long:
                    print(f"      [{i:04d}] 需要 {need} 位元組 > 可用 {have} 位元組: {trans!r}")
                    all_skipped.append(('唇形同步 (LIPSYNC)', f'{lip_name}.LIP', i, orig, trans, have))
            if encode_failed:
                print(f"    注意: 編碼失敗 {len(encode_failed)} 句")
                for i, orig, trans in encode_failed:
                    print(f"      [{i:04d}] 原文: {orig!r} 譯文: {trans!r}")
                    all_skipped.append(('唇形同步 (LIPSYNC)', f'{lip_name}.LIP', i, orig, trans, 0))
            lip_files_done += 1
            total_lip_lines += applied
        else:
            os.remove(out_lip)
    if lip_files_done == 0:
        print("  沒有已翻譯的 LIPSYNC（跳過）")

    print("\n=== 4) 其他執行檔覆蓋層 (APPEND/MGJT 等) ===")
    ovlm_files_done = 0
    total_ovlm_lines = 0
    for name, rel_disc_path in OVLM_FILES:
        template_path = os.path.join(TEMPLATES_DIR, 'OVLM', name + '.txt')
        src_bin = os.path.join(ORIGINAL_DIR, rel_disc_path)
        if not (os.path.exists(template_path) and os.path.exists(src_bin)):
            continue
        out_bin = os.path.join(OUTPUT_DIR, rel_disc_path)
        os.makedirs(os.path.dirname(out_bin), exist_ok=True)
        applied, total, _, skipped = patch_ovlm_file(src_bin, template_path, out_bin, out_font_dir=None)
        if applied > 0:
            print(f"  {name}: {applied}/{total} 字串已套用")
            if skipped:
                print(f"    注意: 找不到指標、無法寫得比原文長 {len(skipped)} 筆")
                for i, orig, trans, orig_len in skipped:
                    print(f"      [{i:04d}] 原文 {orig_len} 位元組: {trans!r}")
                    all_skipped.append(('其他覆蓋層', f'{name} ({rel_disc_path})', i, orig, trans, orig_len))
            ovlm_files_done += 1
            total_ovlm_lines += applied
        else:
            os.remove(out_bin)
    if ovlm_files_done == 0:
        print("  沒有 OVLM 繁中範本（跳過）")

    print("\n=== 4-1) 場所移動/狀態顯示 (MOVE/EYECATCH/CINEMA/ENDING.BIN) ===")
    movecatch_files_done = 0
    total_movecatch_lines = 0
    for template_rel, rel_disc_path in MOVECATCH_FILES:
        template_path = os.path.join(TEMPLATES_DIR, template_rel)
        src_bin = os.path.join(ORIGINAL_DIR, rel_disc_path)
        if not (os.path.exists(template_path) and os.path.exists(src_bin)):
            continue
        out_bin = os.path.join(OUTPUT_DIR, rel_disc_path)
        os.makedirs(os.path.dirname(out_bin), exist_ok=True)
        applied, total, _, too_long = patch_movecatch_file(src_bin, template_path, out_bin, out_font_dir=None)
        if applied > 0:
            name = os.path.basename(rel_disc_path)
            print(f"  {name}: {applied}/{total} 字串已套用")
            if too_long:
                print(f"    注意: 比原文長而放不進去 {len(too_long)} 筆")
                for i, orig, trans, enc_len, orig_len in too_long:
                    print(f"      [{i:04d}] 原文 {orig_len} 位元組: {trans!r}")
                    all_skipped.append(('場所移動/狀態', f'{name}', i, orig, trans, orig_len))
            movecatch_files_done += 1
            total_movecatch_lines += applied
        else:
            os.remove(out_bin)
    if movecatch_files_done == 0:
        print("  沒有 MOVE/EYECATCH 等繁中範本（跳過）")

    print("\n=== 5) 1ST_READ.BIN 全部字串 ===")
    applied_msgs, total_msgs = 0, 0
    all_strings_template = os.path.join(TEMPLATES_DIR, ALL_STRINGS_TEMPLATE_REL)
    if os.path.exists(all_strings_template) and os.path.exists(ORIGINAL_1ST_READ):
        out_1st_read = os.path.join(OUTPUT_DIR, '1ST_READ.BIN')
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        try:
            stats1st = patch_1st_read_file(
                ORIGINAL_1ST_READ, all_strings_template, out_1st_read, out_font_dir=None)
        except SystemExit as e:
            print(f"  {e}")
            print("  跳過 1ST_READ.BIN，其餘繼續。")
            stats1st = None

        if stats1st is None:
            if os.path.exists(out_1st_read):
                os.remove(out_1st_read)
        else:
            applied_msgs = stats1st['applied_inplace'] + stats1st['applied_repoint']
            total_msgs = stats1st['real_total']
            if applied_msgs > 0:
                print(f"  1ST_READ.BIN: {applied_msgs}/{total_msgs} 字串已套用"
                      f" (原地 {stats1st['applied_inplace']}，改指標 {stats1st['applied_repoint']})")
                if stats1st['skipped_no_room']:
                    print(f"  注意: 找不到指標、無法寫得比原文長 {len(stats1st['skipped_no_room'])} 筆")
                    for i, orig, trans, orig_len in stats1st['skipped_no_room']:
                        budget = orig_len // 2
                        print(f"    [{i:03d}] 原文 {orig_len} 位元組（約 {budget} 字）- "
                              f"目前譯文: {trans!r}")
                        all_skipped.append(('系統訊息 (1ST_READ.BIN)', '1ST_READ.BIN', i, orig, trans, orig_len))
            else:
                print("  沒有已翻譯內容（跳過）")
                os.remove(out_1st_read)
    else:
        print("  找不到 translation_templates_cht/1ST_READ/all_1st_read_strings.txt 或 1ST_READ.BIN（跳過）")

    print("\n=== 6) 產生繁體字形 ===")
    cht_map = load_map()
    num_chars = len(cht_map)
    if num_chars > 0:
        patch_skfont(TOOLS_DIR, OUTPUT_DIR, cht_map)
        print(f"  缺字 {num_chars} 個 -> output_cht/ 產生 SKFONT.CG, SKFONT2.CG, SKFONT3.CG, SKFONT4.CG")
    else:
        print("  沒有需要自訂字形的字，未產生字型。")

    print("\n=== 完成 ===")
    print(f"對白檔 {sbx_files_done} 個 ({total_sbx_lines} 行), "
          f"ESM {esm_files_done} 個檔 ({total_esm_lines} 行), "
          f"唇形同步 {lip_files_done} 個檔 ({total_lip_lines} 行), "
          f"其他覆蓋層 {ovlm_files_done} 個檔 ({total_ovlm_lines} 筆), "
          f"場所移動/狀態 {movecatch_files_done} 個檔 ({total_movecatch_lines} 筆), "
          f"1ST_READ.BIN {applied_msgs} 筆, 自訂字形 {num_chars} 字")
    print(f"產出資料夾: {OUTPUT_DIR}")
    print("把這個資料夾 zip 後把副檔名改成 .dcp，")
    print("交給 Universal Dreamcast Patcher 的 Apply Patch。")

    skipped_report_path = os.path.join(BASE_DIR, '長度超過_跳過_清單_cht.txt')
    if all_skipped:
        with open(skipped_report_path, 'w', encoding='utf-8') as f:
            f.write(f"譯文比原文長、本次執行跳過的項目（共 {len(all_skipped)} 筆）\n")
            f.write("這些項目在 output_cht/ 裡仍是日文原文。\n")
            f.write("把譯文縮到原文位元組長度以內後再跑 translate_all_cht.py 即可套用。\n")
            f.write("=" * 70 + "\n\n")
            last_category = None
            for category, filename, i, orig, trans, orig_len in all_skipped:
                if category != last_category:
                    f.write(f"\n--- {category} ---\n")
                    last_category = category
                f.write(f"[{filename}] [{i:04d}] 原文 {orig_len} 位元組\n")
                f.write(f"  原文: {orig}\n")
                f.write(f"  目前譯文（太長）: {trans}\n\n")
        print(f"\n注意: 因比原文長而跳過的項目共 {len(all_skipped)} 筆。")
        print(f"清單: {skipped_report_path}")
    else:
        if os.path.exists(skipped_report_path):
            os.remove(skipped_report_path)


if __name__ == '__main__':
    main()
