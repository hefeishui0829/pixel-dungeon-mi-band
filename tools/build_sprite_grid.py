#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
扫描 Pixel Dungeon 源码, 生成 sprite_grid.json (精灵表 -> 游戏内网格尺寸)。

逻辑
----
对 src/**.java 全文搜索形如:

    texture( Assets.RAT );
    ...
    TextureFilm frames = new TextureFilm( texture, 16, 15 );

的代码段, 提取 Assets 常量名 → 网格 (W, H), 然后用 Assets.java 里
`public static final String X = "foo.png"` 的定义把常量名映射回文件名。

输出
----
tools/sprite_grid.json: {filename: {"w": W, "h": H, "note": "..."}}

这不是运行时必需文件 (convert_sprites.py 启动时若存在则加载, 缺失则退化),
而是给维护者一份"游戏内真实网格 vs 16x16 假设"的对照, 方便校对。
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict


# 抓 Assets.java 的常量 -> 文件名
ASSETS_RE = re.compile(
    r'public\s+static\s+final\s+String\s+(\w+)\s*=\s*"([^"]+)"')

# 抓 Sprite 类里的 texture(Assets.X) + 紧跟的 TextureFilm(W, H)
TEXTURE_RE = re.compile(r'texture\s*\(\s*Assets\.(\w+)\s*\)')
FILM_RE = re.compile(
    r'TextureFilm\s*\(\s*[^,]+\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
# 单参 TextureFilm(texture, N) —— font 用
FILM_ONE_RE = re.compile(r'TextureFilm\s*\(\s*[^,]+\s*,\s*(\d+)\s*\)')
# HeroSprite tiers: TextureFilm(texture, texture.width, FRAME_HEIGHT)
TIERS_RE = re.compile(
    r'TextureFilm\s*\(\s*texture\s*,\s*texture\.width\s*,\s*\w+\s*\)')


def parse_assets(path):
    code = open(path, encoding='utf-8').read()
    return dict(ASSETS_RE.findall(code))


def scan(src_root, assets_path):
    a2f = parse_assets(assets_path)

    # file_constant -> [(sprite_class, W, H)]
    records = defaultdict(list)
    for dp, _, fs in os.walk(src_root):
        for fn in fs:
            if not fn.endswith('.java'):
                continue
            p = os.path.join(dp, fn)
            code = open(p, encoding='utf-8', errors='ignore').read()
            m = TEXTURE_RE.search(code)
            if not m:
                continue
            tex_name = m.group(1)
            snippet = code[m.end(): m.end() + 800]
            m2 = FILM_RE.search(snippet)
            if m2:
                w, h = int(m2.group(1)), int(m2.group(2))
                records[tex_name].append((fn[:-5], w, h))
            elif FILM_ONE_RE.search(snippet):
                records[tex_name].append((fn[:-5], '1arg', None))
            elif TIERS_RE.search(snippet):
                records[tex_name].append((fn[:-5], 'hero-tiers', None))
            else:
                records[tex_name].append((fn[:-5], 'unknown', None))

    out = {}
    for tex_name, lst in records.items():
        fn = a2f.get(tex_name)
        if not fn or not fn.endswith('.png'):
            continue
        cnt = Counter((w, h) for (_, w, h) in lst if isinstance(w, int))
        if cnt:
            (w, h), _ = cnt.most_common(1)[0]
            notes = [x[0] for x in lst if (x[1], x[2]) == (w, h)]
            out[fn] = {'w': w, 'h': h, 'note': '/'.join(notes)[:80]}

    # 标准 16x16 兜底 (无 texture(Assets.X) 引用的图集: items/plants/buffs/badges
    # 等由 ItemSpriteSheet/BuffIndicator 等非 Sprite 类直接管理, 都是 16x16)
    for f in [
        'items.png', 'plants.png', 'buffs.png', 'large_buffs.png',
        'badges.png', 'chrome.png', 'icons.png', 'dashboard.png',
        'status_pane.png', 'hp_bar.png', 'exp_bar.png', 'toolbar.png',
        'shadow.png', 'avatars.png', 'pet.png', 'banners.png',
        'arcs1.png', 'arcs2.png', 'surface.png', 'fireball.png',
        'specks.png', 'effects.png', 'warrior.png', 'mage.png',
        'rogue.png', 'ranger.png', 'spell_icons.png', 'locked_badge.png',
        'amulet.png',
        'tiles0.png', 'tiles1.png', 'tiles2.png', 'tiles3.png', 'tiles4.png',
        'water0.png', 'water1.png', 'water2.png', 'water3.png', 'water4.png',
    ]:
        out.setdefault(f, {'w': 16, 'h': 16, 'note': 'standard'})

    # 字体特殊 (TextureFilm(texture, N) 单参): 等同 16 宽一行
    for f in ['font1x.png', 'font15x.png', 'font2x.png', 'font25x.png',
              'font3x.png']:
        out[f] = {'w': 16, 'h': 16, 'note': 'font-1arg'}

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='Pixel Dungeon src 目录')
    ap.add_argument('--out', default='sprite_grid.json')
    args = ap.parse_args()

    assets_path = os.path.join(args.src, 'com', 'watabou', 'pixeldungeon',
                               'Assets.java')
    grid = scan(args.src, assets_path)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(grid, f, ensure_ascii=False, indent=2, sort_keys=True)

    non = {k: v for k, v in grid.items() if (v['w'], v['h']) != (16, 16)}
    print(f'写 {args.out}: 总 {len(grid)}, 非 16x16 {len(non)}')
    for k, v in sorted(non.items()):
        print(f'  {k:25s} {v["w"]:2d}×{v["h"]:2d}   {v["note"]}')


if __name__ == '__main__':
    main()
