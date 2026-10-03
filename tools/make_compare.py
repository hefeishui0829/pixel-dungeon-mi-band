#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
生成 docs/ 下的视觉对比图。

之所以要脚本化而不是一次性代码: 贴图管线改过之后 (例如修正精灵表网格),
手工对比图会立刻失同步, 而 README 里引用的还是旧图, 形成"文档与产物不一致"。
把这个脚本留在仓库里, 重跑一次就能保证图与当前 output/ 严格对应。

产出
    docs/cmp_tiles.png        tiles0 原图 vs band
    docs/cmp_warrior.png      warrior 原图 vs band
    docs/cmp_items.png        items 原图 vs band
    docs/cmp_all_presets.png  原图 / band-lite / band / band-pro 同 10 个 tile 横向对比
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

BG = (28, 28, 34, 255)          # 深色底, 便于看清半透明边缘
GAP = 6


def root_of():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def load_sheet(out_dir, name):
    """返回 (RGBA ndarray, tile_w, tile_h, coords)"""
    info = json.load(open(os.path.join(out_dir, "sprites.json")))["sheets"][name]
    if info.get("image") is None:
        return None, info
    im = Image.open(os.path.join(out_dir, info["image"])).convert("RGBA")
    return np.asarray(im), info


def orig_tile(src_dir, name, index, gw, gh, cols):
    """从原始素材切第 index 格 (按游戏内网格 gw x gh)"""
    im = Image.open(os.path.join(src_dir, f"{name}.png")).convert("RGBA")
    r, c = divmod(index, cols)
    return im.crop((c * gw, r * gh, (c + 1) * gw, (r + 1) * gh))


def out_tile(arr, info, index, scale):
    """从压缩后图集切第 index 格, 并按 scale 放大到与原图同尺寸便于并列"""
    xy = info["coords"][index] if index < len(info["coords"]) else None
    if xy is None:
        return None
    x, y = xy
    tw, th = info["tileWidth"], info["tileHeight"]
    t = Image.fromarray(arr[y:y + th, x:x + tw], "RGBA")
    if scale != 1:
        t = t.resize((int(round(tw * scale)), int(round(th * scale))), Image.NEAREST)
    return t


def grid_to_image(cells, cols, cell_w, cell_h):
    rows = (len(cells) + cols - 1) // cols
    W = cols * cell_w + (cols - 1) * GAP
    H = rows * cell_h + (rows - 1) * GAP
    canvas = Image.new("RGBA", (W, H), BG)
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        canvas.paste(c, (col * (cell_w + GAP), r * (cell_h + GAP)), c)
    return canvas


def pair_compare(src_dir, out_dir, name, game_grid, n_tile, cols_in_row,
                 scale_up, dest):
    """原图一行 + 压缩后一行 的上下对比图"""
    gw, gh = game_grid
    arr, info = load_sheet(out_dir, name)
    if arr is None:
        print(f"  跳过 {name}: 该图集压缩后为空")
        return False

    # 原图实际列数 (整除, 与游戏 TextureFilm 一致)
    ow = Image.open(os.path.join(src_dir, f"{name}.png")).size[0]
    src_cols = max(1, ow // gw)

    cell_w, cell_h = gw * scale_up, gh * scale_up
    orig_row, out_row = [], []
    for i in range(n_tile):
        o = orig_tile(src_dir, name, i, gw, gh, src_cols)
        o = o.resize((cell_w, cell_h), Image.NEAREST)
        orig_row.append(o)
        t = out_tile(arr, info, i, scale_up * gw / info["tileWidth"])
        out_row.append(t if t else Image.new("RGBA", (cell_w, cell_h), (60, 60, 70, 255)))

    top = grid_to_image(orig_row, cols_in_row, cell_w, cell_h)
    bot = grid_to_image(out_row, cols_in_row, cell_w, cell_h)
    W = max(top.width, bot.width)
    H = top.height + bot.height + GAP * 2
    canvas = Image.new("RGBA", (W, H), BG)
    canvas.paste(top, (0, 0))
    canvas.paste(bot, (0, top.height + GAP * 2))
    canvas.save(dest)
    print(f"  -> {dest}  ({W}x{H})")
    return True


def all_presets(src_dir, out_root, name, game_grid, n_tile, cell, dest):
    """四档横向对比: 原图 + band-lite + band + band-pro"""
    gw, gh = game_grid
    ow = Image.open(os.path.join(src_dir, f"{name}.png")).size[0]
    src_cols = max(1, ow // gw)

    rows = []
    for label, d in (("原图", None), ("band-lite", "band-lite"),
                     ("band", "band"), ("band-pro", "band-pro")):
        cells = []
        for i in range(n_tile):
            if d is None:
                t = orig_tile(src_dir, name, i, gw, gh, src_cols)
                t = t.resize((cell, cell), Image.NEAREST)
            else:
                arr, info = load_sheet(os.path.join(out_root, d), name)
                sc = cell / info["tileWidth"]
                t = out_tile(arr, info, i, sc)
                if t is None:
                    t = Image.new("RGBA", (cell, cell), (60, 60, 70, 255))
            cells.append(t)
        rows.append((label, cells))

    W = n_tile * cell + (n_tile - 1) * GAP
    H = len(rows) * cell + (len(rows) - 1) * GAP
    canvas = Image.new("RGBA", (W, H), BG)
    for r, (_, cells) in enumerate(rows):
        for c, t in enumerate(cells):
            canvas.paste(t, (c * (cell + GAP), r * (cell + GAP)), t)
    canvas.save(dest)
    print(f"  -> {dest}  ({W}x{H})  行序: "
          + " / ".join(l for l, _ in rows))
    return True


def main():
    root = root_of()
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(root, "src-assets", "orig"))
    ap.add_argument("--out", default=os.path.join(root, "output"))
    ap.add_argument("--docs", default=os.path.join(root, "docs"))
    args = ap.parse_args()
    os.makedirs(args.docs, exist_ok=True)

    # (图集名, 游戏内网格, 取几格, 每行几格, 放大倍数)
    print("生成两两对比图 (上行原图 / 下行 band 档):")
    pair_compare(args.src, os.path.join(args.out, "band"), "tiles0",
                 (16, 16), 16, 16, 3, os.path.join(args.docs, "cmp_tiles.png"))
    pair_compare(args.src, os.path.join(args.out, "band"), "warrior",
                 (16, 16), 16, 16, 3, os.path.join(args.docs, "cmp_warrior.png"))
    pair_compare(args.src, os.path.join(args.out, "band"), "items",
                 (16, 16), 16, 16, 3, os.path.join(args.docs, "cmp_items.png"))

    print("生成四档对比图 (统一放大到 48px/tile):")
    all_presets(args.src, args.out, "tiles0", (16, 16), 10, 48,
                os.path.join(args.docs, "cmp_all_presets.png"))
    print("完成。")


if __name__ == "__main__":
    main()
