"""縮短 LIPSYNC 空間不足的繁中譯文，並同步改 SCRIPT。"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools') if False else 'tools')
import hangul_font_map as h

h.set_map_file(os.path.join('tools', 'cht_map.json'))
h.set_space_mode('skip')
mapping = h.load_map()
LINE = re.compile(r'^\[(\d+)\] ?(.*)$')

# old CHT -> new CHT (keep // count of the NEW string matching JP)
REPL = {
    '大家都清楚自己的角色了吧。': '大家都清楚自己角色了吧。',
    '簡單來說……//就是總導演。': '簡單說……//總導演。',
    '簡單說……//就是總導演。': '簡單說……//總導演。',
    '不甘心……//只能到這了……': '不甘心……//只能到這了…',
    '是我輸了！': '我輸了！',
    '那麼，下一場、下一場……': '那麼，下一場……',
    '在先前對黑鬼會一戰活躍的//光武・改上，//加裝追加蒸汽單元，以及……':
        '在先前對黑鬼會一戰活躍的//光武・改上，//加裝追加蒸汽單元……',
    '就是那裡！': '就是那！',
    '多謝光臨！': '每回！',
    '機器人機器人～機器人？': '機人機人～機人？',
    '機器人機器人機器人～！': '機人機人機人～！',
    'Ciao！': 'Ciao',
    '大意就是敵人的啦！': '大意是敵人的啦！',
    '熱烈地……激烈地……閃耀吧！': '熱烈地…激烈地…閃耀！',
    '祝你好運！': '祝好運！',
    '這是懲罰！': '懲罰！',
    '真有兩下！': '有兩下！',
    '不甘心……//只能到這裡了嗎……': '不甘心……//只能到這了…',
    '……我想像了。//……太差勁了。': '……想像了。//……太差勁了。',
    '……筑前煮。': '筑前煮。',
    '那麼，我要向你提出決鬥∈//以隊長為賭注，一決勝負！':
        '那麼，我向你提出決鬥∈//以隊長為賭注，一決勝負！',
    '不過……總有一天，//要分出勝負。//……知道了吧。':
        '不過……總有一天，//分出勝負。//……知道了吧。',
    '嗯，是無所謂啦……//要比的話……//我可不會手下留情喔。':
        '嗯，無所謂啦……//要比的話……//我可不會手下留情。',
    '……來吧。': '…來吧。',
    '那麼，隊長。//祝你有個好夢……': '那麼，隊長。//好夢……',
    '……什麼？': '…什麼？',
    '啊、那個……//我……好難為情。': '啊、那個……//我……害羞。',
    '偏偏在這種時候……//竟然有客人來找隊長……':
        '這種時候……//竟然有客人來找隊長……',
    '這樣啊……': '這樣……',
    '為、為什麼……': '為、為何……',
    '所以，理由什麼的我不知道。//只是……想待在你身邊。//我是這麼覺得的……':
        '所以，理由我不知道。//只是……想待在你身邊。//我這麼覺得……',
    '呵呵呵……//不好意思啊……': '呵呵呵……//不好意思……',
    '大神先生……//請把我……': '大神先生……//把我……',
    '大神先生……好難為情。': '大神先生……害羞。',
    '孩子就是要和父母一起住，//才算幸福//本小姐是這麼想的！':
        '孩子要和父母一起住，//才算幸福，本小姐是這麼想的！',
    '敵方魔操機兵，//正在接近大帝國劇場∈': '敵方魔操機兵，//接近大帝國劇場∈',
    '誰都沒有！': '誰都沒！',
    '這座城市……是……//犯下了過……錯……//不可饒恕……':
        '這座城市……是……//犯下過……錯……//不可饒恕……',
    '也、也就是說……//敵人的真面目是……': '也、也就是說……//敵人真面目是……',
    '瑪莉亞……': '瑪莉亞…',
    '艾莉卡……': '艾莉卡…',
    '長安這傢伙……//打算讓一切歸於虛無嗎！':
        '長安這傢伙……//打算讓一切歸於虛無！',
    '只要和大神先生一起，//就是以一當百喔∈':
        '只要和大神先生一起，//以一當百喔∈',
    '準備完成！//隊長……下達命令∈': '準備完成！//隊長……下令∈',
    '大神先生，就是現在！': '大神先生，現在！',
    '隊長，就是現在！': '隊長，現在！',
    '中尉先生，就是現在的啦！': '中尉先生，現在的啦！',
    '男女啊……//把帝都……未來託付給你們……':
        '男女啊……//帝都……未來託付給你們……',
    '……乾杯。': '…乾杯。',
    '這口紅……//奇怪嗎？': '這口紅……//奇怪？',
}

CHECKS = [
    ('LIPSYNC1', 512, 24), ('LIPSYNC1', 590, 22), ('LIPSYNC1', 827, 8),
    ('LIPSYNC1', 962, 20), ('LIPSYNC1', 1138, 64), ('LIPSYNC1', 1152, 8),
    ('LIPSYNC1', 1229, 8), ('LIPSYNC1', 1234, 16), ('LIPSYNC1', 1235, 18),
    ('LIPSYNC1', 1258, 8), ('LIPSYNC1', 1271, 16), ('LIPSYNC1', 1279, 24),
    ('LIPSYNC1', 1304, 8), ('LIPSYNC1', 1309, 8), ('LIPSYNC1', 1336, 8),
    ('LIPSYNC1', 1347, 24), ('LIPSYNC1', 1386, 8),
    ('LIPSYNC2', 302, 28), ('LIPSYNC2', 365, 8), ('LIPSYNC2', 381, 48),
    ('LIPSYNC2', 384, 46), ('LIPSYNC2', 388, 50), ('LIPSYNC2', 400, 8),
    ('LIPSYNC2', 429, 26), ('LIPSYNC2', 451, 8), ('LIPSYNC2', 643, 26),
    ('LIPSYNC2', 872, 38), ('LIPSYNC2', 1005, 8), ('LIPSYNC2', 1009, 12),
    ('LIPSYNC2', 1015, 66), ('LIPSYNC2', 1118, 24), ('LIPSYNC2', 1128, 22),
    ('LIPSYNC2', 1152, 18), ('LIPSYNC2', 1379, 50), ('LIPSYNC2', 1475, 32),
    ('LIPSYNC2', 1769, 8), ('LIPSYNC2', 1904, 20), ('LIPSYNC2', 2095, 8),
    ('LIPSYNC2', 2172, 8), ('LIPSYNC2', 2177, 16), ('LIPSYNC2', 2178, 18),
    ('LIPSYNC2', 2201, 8), ('LIPSYNC2', 2214, 16), ('LIPSYNC2', 2222, 24),
    ('LIPSYNC2', 2247, 8), ('LIPSYNC2', 2252, 8), ('LIPSYNC2', 2279, 8),
    ('LIPSYNC2', 2290, 24), ('LIPSYNC2', 2329, 8),
    ('LIPSYNC3', 17, 8), ('LIPSYNC3', 61, 50), ('LIPSYNC3', 427, 34),
    ('LIPSYNC3', 506, 8), ('LIPSYNC3', 512, 8), ('LIPSYNC3', 580, 36),
    ('LIPSYNC3', 622, 36), ('LIPSYNC3', 894, 28), ('LIPSYNC3', 939, 18),
    ('LIPSYNC3', 941, 14), ('LIPSYNC3', 944, 16), ('LIPSYNC3', 945, 20),
    ('LIPSYNC3', 946, 12), ('LIPSYNC3', 951, 18), ('LIPSYNC3', 1033, 38),
    ('LIPSYNC3', 1485, 8), ('LIPSYNC3', 1620, 20), ('LIPSYNC3', 1810, 8),
    ('LIPSYNC3', 1887, 8), ('LIPSYNC3', 1892, 16), ('LIPSYNC3', 1893, 18),
    ('LIPSYNC3', 1916, 8), ('LIPSYNC3', 1929, 16), ('LIPSYNC3', 1937, 24),
    ('LIPSYNC3', 1962, 8), ('LIPSYNC3', 1967, 8), ('LIPSYNC3', 1994, 8),
    ('LIPSYNC3', 2005, 24), ('LIPSYNC3', 2044, 8),
    ('LIPSYNC4', 628, 8), ('LIPSYNC4', 759, 18), ('LIPSYNC4', 1062, 8),
    ('LIPSYNC4', 1197, 20), ('LIPSYNC4', 1387, 8), ('LIPSYNC4', 1464, 8),
    ('LIPSYNC4', 1469, 16), ('LIPSYNC4', 1470, 18), ('LIPSYNC4', 1493, 8),
    ('LIPSYNC4', 1506, 16), ('LIPSYNC4', 1514, 24), ('LIPSYNC4', 1539, 8),
    ('LIPSYNC4', 1544, 8), ('LIPSYNC4', 1571, 8), ('LIPSYNC4', 1582, 24),
    ('LIPSYNC4', 1621, 8),
]


def enc_len(s):
    h.assign_tiles(s, mapping)
    return len(h.encode_mixed(s, mapping))


def apply_file(path):
    changed = 0
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            raw = line.rstrip('\r\n')
            eol = line[len(raw):] or '\n'
            m = LINE.match(raw)
            if m and m.group(2) in REPL:
                new = REPL[m.group(2)]
                if new != m.group(2):
                    out.append(f'[{m.group(1)}] {new}{eol}')
                    changed += 1
                    continue
            out.append(line if line.endswith('\n') else line + '\n')
    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(out)
    return changed


def main():
    print('=== 長度預檢 ===')
    bad = 0
    for old, new in REPL.items():
        n = enc_len(new)
        o = enc_len(old)
        print(f'  {o:2d}->{n:2d}  {new}')
    print()
    roots = [
        os.path.join('translation_templates_cht', 'LIPSYNC'),
        os.path.join('translation_templates_cht', 'ADVDATA', 'SCRIPT'),
    ]
    total = 0
    for root in roots:
        for name in sorted(os.listdir(root)):
            if name.endswith('.txt'):
                n = apply_file(os.path.join(root, name))
                if n:
                    print(f'{name}: {n} 行')
                    total += n
    print(f'共改 {total} 行\n=== LIPSYNC 預算核對 ===')
    for fn, idx, budget in CHECKS:
        path = os.path.join('translation_templates_cht', 'LIPSYNC', fn + '.txt')
        text = None
        with open(path, encoding='utf-8') as f:
            for line in f:
                m = LINE.match(line.rstrip('\n'))
                if m and int(m.group(1)) == idx:
                    text = m.group(2)
                    break
        n = enc_len(text)
        ok = 'OK' if n <= budget else 'FAIL'
        if n > budget:
            bad += 1
            print(f'  {ok} {fn}[{idx:04d}] {n}/{budget} {text}')
    if bad:
        print(f'仍超長 {bad} 句')
        sys.exit(1)
    print('全部在預算內')
    h.save_map(mapping)


if __name__ == '__main__':
    main()
