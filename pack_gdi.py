"""
把 translate_all.py 的 output/ 套進原版 Dreamcast GDI，寫出新的 GDI。

output/ 只有被改過的檔，不是整張光碟。音軌、IP.BIN 與沒改到的檔
都留在原版 GDI 裡，這支程式只替換資料軌上同路徑的檔案。

用法（在專案根目錄）:
  python pack_gdi.py --gdi D:\\sw4\\game.gdi --patch output --dest gdi_out

  python pack_gdi.py --gdi D:\\sw4\\game.gdi --dry-run
"""
import argparse
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
SYNC = bytes([0x00]) + b'\xFF' * 10 + bytes([0x00])
USER_DATA = 2048


def pack_both16(n):
    return struct.pack('<H', n) + struct.pack('>H', n)


def pack_both32(n):
    return struct.pack('<I', n) + struct.pack('>I', n)


def read_both32(buf, offset):
    le = struct.unpack_from('<I', buf, offset)[0]
    be = struct.unpack_from('>I', buf, offset + 4)[0]
    return le if le == be else le


def norm_key(path):
    path = path.replace('\\', '/').strip('/')
    if ';' in path:
        path = path.split(';', 1)[0]
    return path.casefold()


def _edc_table():
    table = []
    for i in range(256):
        edc = i
        for _ in range(8):
            if edc & 1:
                edc = (edc >> 1) ^ 0xD8018001
            else:
                edc >>= 1
        table.append(edc & 0xFFFFFFFF)
    return table


_EDC_TABLE = _edc_table()


def edc_compute(data):
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ _EDC_TABLE[(edc ^ b) & 0xFF]
    return edc & 0xFFFFFFFF


def _ecc_luts():
    """ECMA-130 GF(2^8) multiply-by-2 table, and discrete log."""
    mul2 = [0] * 256
    for i in range(256):
        x = i << 1
        if i & 0x80:
            x ^= 0x11D
        mul2[i] = x & 0xFF
    log = [0] * 256
    x = 1
    for i in range(255):
        log[x] = i
        x = mul2[x]
    return mul2, log


_ECC_MUL2, _ECC_LOG = _ecc_luts()


def _ecc_block(buf, base, major_count, minor_count, major_mult, minor_inc, dest):
    size = major_count * minor_count
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _minor in range(minor_count):
            temp = buf[base + index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_b ^= temp
            ecc_a = _ECC_MUL2[ecc_a ^ temp]
        mixed = _ECC_MUL2[ecc_a] ^ ecc_b
        parity = _ECC_LOG[mixed]
        buf[dest + major] = parity
        buf[dest + major_count + major] = parity ^ ecc_b


def fix_mode1(raw):
    """重算 Mode 1 的 EDC／ECC。raw 必須是 2352 位元組，使用者資料已在 [16:2064]。"""
    raw = bytearray(raw)
    if len(raw) != 2352:
        raise ValueError('Mode 1 區段必須是 2352 位元組')
    struct.pack_into('<I', raw, 2064, edc_compute(raw[:2064]))
    raw[2068:2076] = b'\x00' * 8
    # P 用標頭到保留位，Q 還要含剛剛寫好的 P。
    _ecc_block(raw, 12, 86, 24, 2, 86, 2076)
    _ecc_block(raw, 12, 52, 43, 86, 88, 2248)
    return bytes(raw)


def bcd(n):
    return ((n // 10) << 4) | (n % 10)


def unbcd(n):
    return (n >> 4) * 10 + (n & 0x0F)


def add_msf(header4, frames):
    m = unbcd(header4[0])
    s = unbcd(header4[1])
    f = unbcd(header4[2])
    mode = header4[3]
    total = ((m * 60) + s) * 75 + f + frames
    if total < 0:
        total = 0
    f = total % 75
    total //= 75
    s = total % 60
    m = total // 60
    return bytes([bcd(m), bcd(s), bcd(f), mode])


class TrackFile:
    def __init__(self, path, sector_size, file_offset, writable, disc_lba=0):
        self.path = Path(path)
        self.sector_size = sector_size
        self.file_offset = file_offset
        self.disc_lba = disc_lba
        self.absolute = False
        self.append_base = 0
        self.fh = open(self.path, 'r+b' if writable else 'rb')
        self.fh.seek(0, os.SEEK_END)
        self.file_size = self.fh.tell()
        self.kind = 'raw2048'
        self.data_off = 0
        self.base_header = bytes([0, 2, 0, 1])
        if sector_size == 2352 and self.file_size >= 2352:
            first = self.read_raw(0)
            if first[:12] == SYNC:
                mode = first[15]
                self.base_header = bytes(first[12:16])
                if mode == 2:
                    self.kind = 'mode2'
                    self.data_off = 24
                else:
                    self.kind = 'mode1'
                    self.data_off = 16
        self.vd_sectors = []
        self.next_lba = 0
        self.volume_space = 0

    def close(self):
        self.fh.close()

    def sector_count(self):
        payload = max(0, self.file_size - self.file_offset)
        return payload // self.sector_size

    def read_raw(self, lba):
        self.fh.seek(self.file_offset + lba * self.sector_size)
        data = self.fh.read(self.sector_size)
        if len(data) < self.sector_size:
            data = data + bytes(self.sector_size - len(data))
        return data

    def write_raw(self, lba, raw):
        if len(raw) != self.sector_size:
            raise ValueError('區段長度不符')
        pos = self.file_offset + lba * self.sector_size
        self.fh.seek(pos)
        self.fh.write(raw)
        end = pos + self.sector_size
        if end > self.file_size:
            self.file_size = end

    def synthesize(self, lba):
        if self.kind == 'raw2048':
            return bytes(USER_DATA)
        raw = bytearray(2352)
        raw[:12] = SYNC
        raw[12:16] = add_msf(self.base_header, lba)
        if self.kind == 'mode1':
            return fix_mode1(raw)
        return bytes(raw)

    def ensure_sector(self, lba):
        pos = self.file_offset + (lba + 1) * self.sector_size
        if self.file_size >= pos:
            return
        self.write_raw(lba, self.synthesize(lba))

    def read_user(self, lba):
        self.ensure_sector(lba)
        raw = self.read_raw(lba)
        return raw[self.data_off:self.data_off + USER_DATA]

    def write_user(self, lba, data):
        if len(data) != USER_DATA:
            raise ValueError('使用者資料必須是 2048 位元組')
        self.ensure_sector(lba)
        if self.kind == 'raw2048':
            self.write_raw(lba, data)
            return
        raw = bytearray(self.read_raw(lba))
        if raw[:12] != SYNC:
            raw = bytearray(self.synthesize(lba))
        raw[self.data_off:self.data_off + USER_DATA] = data
        if self.kind == 'mode1':
            raw = bytearray(fix_mode1(raw))
        self.write_raw(lba, raw)

    def to_file(self, iso_lba):
        """目錄裡的 LBA。GD-ROM 高密度軌常用光碟絕對位址，要扣掉軌起點。"""
        if self.absolute:
            rel = iso_lba - self.disc_lba
            if rel < 0:
                raise SystemExit(f'LBA {iso_lba} 比資料軌起點 {self.disc_lba} 還小')
            return rel
        return iso_lba

    def to_iso(self, file_lba):
        if self.absolute:
            return file_lba + self.disc_lba
        return file_lba

    def read_extent(self, lba, size):
        out = bytearray()
        remain = size
        n = 0
        while remain > 0:
            chunk = self.read_user(lba + n)
            take = min(remain, USER_DATA)
            out += chunk[:take]
            remain -= take
            n += 1
        return bytes(out)


class FileRec:
    def __init__(self, track, sector, offset, extent, size):
        self.track = track
        self.sector = sector
        self.offset = offset
        self.extent = extent
        self.size = size


def parse_gdi(gdi_path):
    text = Path(gdi_path).read_text(encoding='utf-8', errors='replace')
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f'GDI 是空的: {gdi_path}')
    try:
        count = int(lines[0].split()[0])
    except ValueError as e:
        raise SystemExit(f'GDI 第一行不是軌數: {gdi_path}') from e
    tracks = []
    base = Path(gdi_path).resolve().parent
    for line in lines[1:count + 1]:
        parts = line.split()
        if len(parts) < 6:
            raise SystemExit(f'GDI 軌描述無法解析: {line}')
        number = int(parts[0])
        lba = int(parts[1])
        ctrl = int(parts[2])
        sector_size = int(parts[3])
        offset = int(parts[-1])
        name = ' '.join(parts[4:-1]).strip('"')
        path = Path(name)
        if not path.is_absolute():
            path = base / path
        tracks.append({
            'number': number,
            'lba': lba,
            'ctrl': ctrl,
            'sector_size': sector_size,
            'offset': offset,
            'name': Path(name).name,
            'path': path.resolve(),
        })
    if len(tracks) != count:
        raise SystemExit(f'GDI 宣告 {count} 軌，實際讀到 {len(tracks)} 軌')
    return tracks


def slice_length(tracks, index):
    """同一實體檔裡，這一軌佔用的位元組數。"""
    cur = tracks[index]
    same = [t for t in tracks if t['path'] == cur['path']]
    same.sort(key=lambda t: t['offset'])
    for i, t in enumerate(same):
        if t is cur or (t['offset'] == cur['offset'] and t['number'] == cur['number']):
            if i + 1 < len(same):
                return same[i + 1]['offset'] - cur['offset']
            return None
    return None


def copy_track(src, dest, offset, length):
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(src, 'rb') as inp, open(dest, 'wb') as out:
        inp.seek(offset)
        remaining = length
        while True:
            if remaining is None:
                chunk = inp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
            else:
                if remaining <= 0:
                    break
                chunk = inp.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)


def _safe_name(name):
    shown = ''.join(ch if ch.isprintable() else '·' for ch in name)
    if len(shown) > 40:
        shown = shown[:40] + '…'
    return shown


def walk_dir(track, extent, size, prefix, joliet, index):
    data = track.read_extent(track.to_file(extent), size)
    pos = 0
    while pos + 33 < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            if pos % USER_DATA == 0:
                break
            pos = (pos // USER_DATA + 1) * USER_DATA
            continue
        if pos + rec_len > len(data) or rec_len < 34:
            break
        fi_len = data[pos + 32]
        if pos + 33 + fi_len > len(data):
            break
        flags = data[pos + 25]
        gap = data[pos + 27]
        ext_attr = data[pos + 1]
        ident = bytes(data[pos + 33:pos + 33 + fi_len])
        extent_lba = read_both32(data, pos + 2)
        data_len = read_both32(data, pos + 10)
        sector = track.to_file(extent) + (pos // USER_DATA)
        offset = pos % USER_DATA
        pos += rec_len
        if ident in (b'\x00', b'\x01'):
            continue
        if joliet:
            try:
                name = ident.decode('utf-16-be')
            except UnicodeDecodeError:
                continue
        else:
            name = ident.decode('latin-1')
        if ';' in name:
            name = name.split(';', 1)[0]
        if gap or ext_attr:
            print(f'  略過交錯／延伸屬性檔: {_safe_name(prefix + name)}')
            continue
        if flags & 0x02:
            walk_dir(track, extent_lba, data_len, prefix + name + '/', joliet, index)
            continue
        key = norm_key(prefix + name)
        index.setdefault(key, []).append(FileRec(track, sector, offset, extent_lba, data_len))


def index_track(track):
    index = {}
    if track.sector_count() <= 16:
        return index
    sector_lba = 16
    primary_space = None
    while sector_lba < track.sector_count():
        sec = track.read_user(sector_lba)
        if sec[1:6] != b'CD001':
            break
        kind = sec[0]
        if kind == 255:
            break
        if kind in (1, 2):
            block = struct.unpack_from('<H', sec, 128)[0]
            if block not in (0, USER_DATA):
                print(f'  區段 {sector_lba} 的邏輯區段大小是 {block}，略過')
            else:
                space = read_both32(sec, 80)
                if kind == 1 or primary_space is None:
                    primary_space = space
                track.vd_sectors.append(sector_lba)
                joliet = kind == 2 and sec[88:91] in (b'%/@', b'%/C', b'%/E')
                root = sec[156:156 + sec[156]]
                if len(root) >= 34:
                    root_extent = read_both32(root, 2)
                    if kind == 1 and track.disc_lba and root_extent >= track.disc_lba:
                        track.absolute = True
                    walk_dir(
                        track,
                        root_extent,
                        read_both32(root, 10),
                        '',
                        joliet or (kind == 2),
                        index,
                    )
        sector_lba += 1
        if sector_lba > 16 + 32:
            break
    track.volume_space = primary_space or track.sector_count()
    if track.absolute:
        # 高密度軌的目錄 LBA 是光碟絕對位址，卷大小則是軌內區段數。
        # 變長的檔接到檔尾，避免覆寫中間的檔。
        track.next_lba = track.sector_count()
    else:
        track.next_lba = track.volume_space
    track.append_base = track.next_lba
    return index


def list_patch_files(patch_dir):
    files = []
    for path in patch_dir.rglob('*'):
        if path.is_file():
            rel = path.relative_to(patch_dir).as_posix()
            files.append((norm_key(rel), rel, path))
    return files


def sectors_needed(size):
    return (size + USER_DATA - 1) // USER_DATA


def update_record(rec, extent, size):
    sec = bytearray(rec.track.read_user(rec.sector))
    sec[rec.offset + 2:rec.offset + 10] = pack_both32(extent)
    sec[rec.offset + 10:rec.offset + 18] = pack_both32(size)
    rec.track.write_user(rec.sector, bytes(sec))
    rec.extent = extent
    rec.size = size


def write_extent(track, iso_lba, data):
    lba = track.to_file(iso_lba)
    for i in range(0, len(data), USER_DATA):
        chunk = data[i:i + USER_DATA]
        if len(chunk) < USER_DATA:
            chunk = chunk + bytes(USER_DATA - len(chunk))
        track.write_user(lba + (i // USER_DATA), chunk)


def update_volume_space(track):
    added = track.next_lba - track.append_base
    if added == 0:
        return
    if track.absolute:
        new_space = track.volume_space + added
    else:
        new_space = track.next_lba
    for lba in track.vd_sectors:
        sec = bytearray(track.read_user(lba))
        if sec[1:6] != b'CD001' or sec[0] not in (1, 2):
            continue
        sec[80:88] = pack_both32(new_space)
        track.write_user(lba, bytes(sec))
    track.volume_space = new_space


def plan_replacements(index, patch_files):
    found = []
    missing = []
    for key, rel, path in patch_files:
        recs = index.get(key)
        if not recs:
            missing.append(rel)
            continue
        found.append((rel, path, recs))
    return found, missing


def apply_replacements(found, dry_run):
    grown = 0
    for rel, path, recs in found:
        data = path.read_bytes()
        group = {}
        for rec in recs:
            group.setdefault((id(rec.track), rec.extent, rec.size), []).append(rec)
        for recs_same in group.values():
            rec = recs_same[0]
            old_sectors = sectors_needed(rec.size) if rec.size else 0
            new_sectors = sectors_needed(len(data)) if data else 0
            if new_sectors <= old_sectors and old_sectors:
                extent = rec.extent
                where = '原地'
            else:
                extent = None if dry_run else rec.track.alloc_lba(len(data) if data else USER_DATA)
                where = '加到資料軌尾端' if data else '清空'
                grown += 1
            print(f'  {rel}: {rec.size} -> {len(data)} 位元組（{where}）')
            if dry_run:
                continue
            if extent is None:
                extent = rec.track.alloc_lba(len(data) if data else USER_DATA)
            if data:
                write_extent(rec.track, extent, data)
            for item in recs_same:
                update_record(item, extent, len(data))
    return grown


def alloc_lba(self, nbytes):
    nsec = max(1, sectors_needed(nbytes))
    file_lba = self.next_lba
    self.next_lba += nsec
    for i in range(nsec):
        self.ensure_sector(file_lba + i)
    return self.to_iso(file_lba)


TrackFile.alloc_lba = alloc_lba


def pack(gdi_path, patch_dir, dest, dry_run=False):
    gdi_path = Path(gdi_path).resolve()
    patch_dir = Path(patch_dir).resolve()
    dest = Path(dest)
    if not gdi_path.is_file():
        raise SystemExit(f'找不到原版 GDI: {gdi_path}')
    if not patch_dir.is_dir():
        raise SystemExit(f'找不到補丁資料夾: {patch_dir}')
    patch_files = list_patch_files(patch_dir)
    if not patch_files:
        raise SystemExit(f'補丁資料夾是空的: {patch_dir}')

    tracks = parse_gdi(gdi_path)
    if dest.suffix.lower() == '.gdi':
        dest_gdi = dest
        dest_dir = dest.parent
    else:
        dest_dir = dest
        dest_gdi = dest_dir / gdi_path.name
    dest_dir = dest_dir.resolve()
    dest_gdi = dest_gdi.resolve()

    data_tracks = [t for t in tracks if t['ctrl'] & 0x4]
    if not data_tracks:
        raise SystemExit('GDI 裡沒有資料軌')

    print(f'原版: {gdi_path}')
    print(f'補丁: {patch_dir}（{len(patch_files)} 個檔）')
    if dry_run:
        print('預覽，不會寫入映像')
    else:
        print(f'輸出: {dest_gdi}')
        dest_dir.mkdir(parents=True, exist_ok=True)

    opened = []
    index = {}
    try:
        for t in tracks:
            if not t['path'].is_file():
                raise SystemExit(f'找不到軌檔: {t["path"]}')
            out_name = t['name']
            out_path = dest_dir / out_name
            if not dry_run:
                if out_path.resolve() == t['path'].resolve():
                    raise SystemExit(f'輸出會覆寫原版軌 {out_path}，請改 --dest')
                length = slice_length(tracks, tracks.index(t))
                print(f'複製軌 {t["number"]}: {t["name"]}')
                copy_track(t['path'], out_path, t['offset'], length)
                use_path = out_path
                use_offset = 0
            else:
                use_path = t['path']
                use_offset = t['offset']
            if t['ctrl'] & 0x4:
                track = TrackFile(
                    use_path, t['sector_size'], use_offset,
                    writable=not dry_run, disc_lba=t['lba'])
                opened.append(track)
                found = index_track(track)
                print(f'資料軌 {t["number"]}: 索引到 {len(found)} 個檔')
                for key, recs in found.items():
                    index.setdefault(key, []).extend(recs)

        found, missing = plan_replacements(index, patch_files)
        if not index:
            raise SystemExit('資料軌裡沒有讀到 ISO9660 檔案')
        print(f'將套用 {len(found)} 個檔，光碟上找不到 {len(missing)} 個')
        for rel in missing:
            print(f'  找不到: {rel}')
        apply_replacements(found, dry_run)
        if not dry_run:
            touched = {id(rec.track) for _rel, _path, recs in found for rec in recs}
            for track in opened:
                if id(track) in touched:
                    update_volume_space(track)
            lines = [str(len(tracks))]
            for t in tracks:
                lines.append(
                    f'{t["number"]} {t["lba"]} {t["ctrl"]} {t["sector_size"]} {t["name"]} 0'
                )
            dest_gdi.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            print(f'完成: {dest_gdi}')
    finally:
        for track in opened:
            track.close()

    if not found:
        return 1
    if missing:
        print(f'有 {len(missing)} 個補丁檔不在光碟上，已略過')
    return 0


def _dir_record(extent, size, name, is_dir=False):
    fi_len = len(name)
    rec_len = 33 + fi_len
    if rec_len % 2:
        rec_len += 1
    rec = bytearray(rec_len)
    rec[0] = rec_len
    rec[2:10] = pack_both32(extent)
    rec[10:18] = pack_both32(size)
    rec[25] = 0x02 if is_dir else 0
    rec[28:32] = pack_both16(1)
    rec[32] = fi_len
    rec[33:33 + fi_len] = name
    return bytes(rec)


def _blank_vd(kind):
    sec = bytearray(USER_DATA)
    sec[0] = kind
    sec[1:6] = b'CD001'
    sec[6] = 1
    return sec


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / 'src'
        src.mkdir()
        track_path = src / 'track03.bin'
        nsec = 22
        image = bytearray(nsec * USER_DATA)
        pvd = _blank_vd(1)
        pvd[40:43] = b'SW4'
        pvd[80:88] = pack_both32(nsec)
        pvd[120:124] = pack_both16(1)
        pvd[124:128] = pack_both16(1)
        pvd[128:132] = pack_both16(USER_DATA)
        pvd[156:190] = _dir_record(19, USER_DATA, b'\x00', True)
        image[16 * USER_DATA:(17 * USER_DATA)] = pvd

        joliet = _blank_vd(2)
        joliet[80:88] = pack_both32(nsec)
        joliet[88:91] = b'%/@'
        joliet[120:124] = pack_both16(1)
        joliet[124:128] = pack_both16(1)
        joliet[128:132] = pack_both16(USER_DATA)
        joliet[156:190] = _dir_record(20, USER_DATA, b'\x00', True)
        image[17 * USER_DATA:(18 * USER_DATA)] = joliet

        image[18 * USER_DATA:(19 * USER_DATA)] = _blank_vd(255)

        primary = bytearray(USER_DATA)
        recs = b''.join([
            _dir_record(19, USER_DATA, b'\x00', True),
            _dir_record(19, USER_DATA, b'\x01', True),
            _dir_record(21, 3, b'HELLO.BIN'),
        ])
        primary[:len(recs)] = recs
        image[19 * USER_DATA:(20 * USER_DATA)] = primary

        uni = 'HELLO.BIN'.encode('utf-16-be')
        joliet_dir = bytearray(USER_DATA)
        recs = b''.join([
            _dir_record(20, USER_DATA, b'\x00', True),
            _dir_record(20, USER_DATA, b'\x01', True),
            _dir_record(21, 3, uni),
        ])
        joliet_dir[:len(recs)] = recs
        image[20 * USER_DATA:(21 * USER_DATA)] = joliet_dir
        image[21 * USER_DATA:21 * USER_DATA + 3] = b'OLD'
        track_path.write_bytes(image)
        (src / 'game.gdi').write_text('1\n1 45000 4 2048 track03.bin 0\n', encoding='utf-8')

        patch = tmp / 'patch'
        (patch / 'subdir').mkdir(parents=True)
        payload = b'NEW' * 1000
        # 路徑在光碟根目錄
        (patch / 'HELLO.BIN').write_bytes(payload)

        dest = tmp / 'out.gdi'
        code = pack(src / 'game.gdi', patch, dest)
        if code != 0:
            raise SystemExit(f'self-test 結束碼 {code}')
        out_track = TrackFile(tmp / 'track03.bin', USER_DATA, 0, writable=False)
        try:
            sec = out_track.read_user(19)
            extent = read_both32(sec, 2 + 34 + 34)
            # 第三筆目錄紀錄的起點
            hello = sec
            pos = 0
            target = None
            while pos + 34 <= len(hello) and hello[pos]:
                ident = bytes(hello[pos + 33:pos + 33 + hello[pos + 32]])
                if ident.startswith(b'HELLO'):
                    target = pos
                    break
                pos += hello[pos]
            if target is None:
                raise SystemExit('self-test 找不到 HELLO.BIN 目錄紀錄')
            new_extent = read_both32(hello, target + 2)
            new_size = read_both32(hello, target + 10)
            if new_size != len(payload):
                raise SystemExit(f'self-test 大小錯誤 {new_size}')
            body = out_track.read_extent(new_extent, new_size)
            if body != payload:
                raise SystemExit('self-test 讀回內容不符')
            space = read_both32(out_track.read_user(16), 80)
            if space < new_extent + sectors_needed(len(payload)):
                raise SystemExit(f'self-test 卷大小不足 {space}')
            jsec = out_track.read_user(20)
            jsize = None
            pos = 0
            while pos + 34 <= len(jsec) and jsec[pos]:
                ident = bytes(jsec[pos + 33:pos + 33 + jsec[pos + 32]])
                if ident == uni:
                    jsize = read_both32(jsec, pos + 10)
                    jext = read_both32(jsec, pos + 2)
                    break
                pos += jsec[pos]
            if jsize != len(payload) or jext != new_extent:
                raise SystemExit('self-test Joliet 目錄沒更新')
        finally:
            out_track.close()

        # Mode 1：EDC 兩次計算要相同，且改資料後 EDC 會變。
        raw = bytearray(2352)
        raw[:12] = SYNC
        raw[12:16] = bytes([0x00, 0x02, 0x00, 0x01])
        raw[100] = 0x5A
        a = fix_mode1(raw)
        b = fix_mode1(a)
        if a != b:
            raise SystemExit('self-test Mode 1 重算不穩定')
        if edc_compute(a[:2064]) != struct.unpack_from('<I', a, 2064)[0]:
            raise SystemExit('self-test EDC 不符')
    print('self-test 通過')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gdi', help='原版 .gdi 路徑')
    parser.add_argument('--patch', default=str(ROOT / 'output'), help='補丁資料夾，預設是 output')
    parser.add_argument('--dest', default=str(ROOT / 'gdi_out'), help='輸出 .gdi 檔或資料夾，預設是 gdi_out')
    parser.add_argument('--dry-run', action='store_true', help='只列出會替換的檔，不寫入')
    parser.add_argument('--self-test', action='store_true', help='跑內建的小型 ISO 測試')
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if not args.gdi:
        parser.error('請用 --gdi 指定原版 .gdi')
    raise SystemExit(pack(args.gdi, args.patch, args.dest, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
