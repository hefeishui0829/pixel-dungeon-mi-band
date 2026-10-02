#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
应用启动图标转换: 像素地牢 ic_launcher (192x192 RGBA) -> 手环快应用图标

与 convert_sprites.py 的区别:
  图标是单张整图, 不是 tile 图集, 因此不做切片/去重/重打包,
  只做「缩放 + 硬边二值化 + 调色板量化 + PNG-8」。

  调色板/索引映射/PNG-8 写出全部复用 convert_sprites 里已验证的实现
  (自己重写容易踩 PNG-8 索引上限 255 的坑)。

输出尺寸:
  手环快应用 manifest 的 icon 字段不强制固定尺寸, 系统会自动缩放。
  这里输出 108x108 (快应用常见标准) + 192x192 (原尺寸) 两版, 按需在 manifest 里选。
"""
import argparse
import os
import shutil
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from convert_sprites import binarize_alpha, build_palette, save_indexed  # noqa: E402

SIZES = [(108, "icon.png"), (192, "icon@192.png")]


def main():
    ap = argparse.ArgumentParser(description="像素地牢启动图标 -> 手环快应用图标")
    ap.add_argument("--src", default=os.path.join(ROOT, "src-assets", "orig-app-icon",
                                                  "ic_launcher_192.png"))
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "app-icon"))
    ap.add_argument("--demo-img", default=os.path.join(ROOT, "demo", "src", "img"),
                    help="同时拷一份 icon.png 到快应用工程")
    ap.add_argument("--colors", type=int, default=64)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    src = Image.open(args.src).convert("RGBA")
    src_kb = os.path.getsize(args.src) / 1024
    print(f"源图标: {args.src}  {src.size[0]}x{src.size[1]}  {src_kb:.1f} KB")
    print("-" * 62)

    for size, name in SIZES:
        scaled = src if size == src.size[0] else src.resize((size, size), Image.BOX)
        canvas = np.array(binarize_alpha(scaled, 128))
        pal = build_palette([canvas], args.colors)
        out_path = os.path.join(args.out, name)
        save_indexed(canvas, pal, out_path)
        dst_kb = os.path.getsize(out_path) / 1024

        # 自检: 量化后不透明区平均色 vs 源, 偏差过大说明调色板有问题
        a = np.array(scaled)
        m = a[..., 3] > 128
        ref = a[..., :3][m].mean(0)
        got = canvas[..., :3][m].mean(0)
        delta = np.abs(ref - got).mean()
        flag = "OK" if delta < 12 else f"偏色! delta={delta:.1f}"
        print(f"  {name:<14} {size}x{size}  {len(pal):>3} 色  {dst_kb:5.1f} KB  "
              f"({src_kb / dst_kb:.1f}x)  {flag}")

    os.makedirs(args.demo_img, exist_ok=True)
    shutil.copy(os.path.join(args.out, "icon.png"), os.path.join(args.demo_img, "icon.png"))
    print(f"\n已拷贝到 {args.demo_img}/icon.png (manifest.json 的 icon 字段指向它)")


if __name__ == "__main__":
    main()
