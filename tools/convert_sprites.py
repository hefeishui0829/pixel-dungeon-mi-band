#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# 本脚本自身以 MIT 许可发布 (不引用任何 GPL 素材, 素材由 --src 参数在运行时指定)。
# 注意: 脚本输出的贴图是输入素材的派生物, 其许可随输入素材 (像素地牢为 GPL-3.0)。
"""
Pixel Dungeon 美术素材 -> 小米手环 Vela 快应用 低精度贴图 批量转换管线
================================================================================

来源素材
    https://github.com/watabou/pixel-dungeon (commit ca458a2, v1.9.1, GPL-3.0)
    原图集全部是 16x16 像素网格的像素画精灵表 (spritesheet)。

目标设备 (小米 Vela JS 快应用 / 小米手环)
    小米手环 9     胶囊屏  192 x 490   PPI 325   屏幕宽度 96dp   长宽比 0.4
    小米手环 10    胶囊屏  212 x 520   PPI 326   屏幕宽度 106dp  长宽比 0.4
    小米手环 8 Pro 矩形屏  336 x 480   PPI 336   屏幕宽度 168dp  长宽比 0.7
    小米手环 9 Pro 矩形屏  336 x 480   PPI 336   屏幕宽度 168dp  长宽比 0.7
    (数据来源: https://iot.mi.com/vela/quickapp/zh/guide/multi-screens/)

手环的硬约束
    1. 屏幕物理像素极小 -> 16px 的 tile 已接近可辨识下限，降分辨率几乎不损失观感
    2. 包体/内存极受限 -> 贴图必须小，PNG-8 索引色比 RGBA32 省 3~5 倍
    3. CPU 弱、带宽小 -> 图集尺寸不要超过 512px，单图解码才不会卡

本管线做的事
    step 1  按 16px 网格切分原始精灵表 (个别表用 32px / 8px / 异形网格)
    step 2  alpha 预乘后缩放 (避免透明黑边污染缩放结果), 再反预乘
    step 3  alpha 二值化: >= 阈值的设 255, 其余设 0 -> 恢复像素画硬边, 去掉抗锯齿
    step 4  全库统一调色板量化 (median-cut) -> 颜色数从 7042 降到 16~48 色
    step 5  空白 tile 剔除 + 内容去重 -> 多个 id 复用同一块图集区域
    step 6  紧凑重排打包, 输出 PNG-8 (索引色 + tRNS 二值透明)
    step 7  产出 manifest JSON / JS 模块, 供快应用直接按 id 取图

用法
    python3 tools/convert_sprites.py                       # 默认生成 band + band-lite 两档
    python3 tools/convert_sprites.py --preset band-pro     # 只生成 16px 高清档
    python3 tools/convert_sprites.py --tile 10 --colors 24 --preset custom
    python3 tools/convert_sprites.py --png-mode rgba       # 输出 RGBA32 而非 PNG-8(兼容性兜底)
"""

import argparse
import json
import math
import os
import sys
from collections import OrderedDict

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------- #
# 1. 精灵表网格配置
# --------------------------------------------------------------------------- #

DEFAULT_TILE = (16, 16)

# 精灵表网格配置: 一部分是显式声明的特效 / 水面 / 字体等;
# 另一部分来自 tools/sprite_grid.json —— 由扫描 PD v1.9.1 源码里所有
#   texture( Assets.X ); TextureFilm(texture, W, H)
# 自动得到, 反映游戏内真实的网格尺寸。
#
# 历史教训: 之前只用显式 TILE_OVERRIDES, 导致 mob/npc 类图集按 16x16 错误切
# (例如 piranha.png 实际是 12x16 网格, scorphio 是 18x17, rat 是 16x15 等等)。
# 这会让所有非 16x16 图集在游戏内的动画帧位置整体错位, 是隐蔽但严重的 bug。

TILE_OVERRIDES = {
    # 大尺寸图标 / 特效
    "large_buffs": (32, 32),
    "amulet": (32, 32),
    "arcs1": (32, 32),
    "arcs2": (32, 32),
    "effects": (16, 16),
    # 水面纹理 (32x32 无缝贴图, 无 alpha)
    **{f"water{i}": (32, 32) for i in range(5)},
    # 异形小图
    "shadow": (4, 4),
    "specks": (8, 8),
    "larva": (12, 8),       # PiranhaSprite 后的 larva: TextureFilm(texture, 12, 8)
    "exp_bar": (16, 1),     # 单行条: TextureFilm(texture, texture.width, 1)
    "hp_bar": (16, 4),
    # 点阵字体 (按游戏内 TextureFilm(texture, 16) 单参, 即 16 像素列)
    "font1x": (8, 8),
    "font15x": (16, 16),
    "font2x": (16, 16),
    "font25x": (16, 32),
    "font3x": (32, 32),
}

# 启动时由 _load_sprite_grid() 把 sprite_grid.json 里的 30 张非 16x16
# 图集网格注入 TILE_OVERRIDES, 覆盖上面默认值 (如水/字体之外的非 16x16)。

def _load_sprite_grid():
    """从 sprite_grid.json 加载游戏内网格尺寸到 TILE_OVERRIDES。

    该 json 由 tools/build_sprite_grid.py 生成 (解析 Pixel Dungeon 源码里所有
    `texture(Assets.X); TextureFilm(texture, W, H)` 调用)。如果缺失则跳过,
    退化到脚本内的 TILE_OVERRIDES。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "sprite_grid.json")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        grid = json.load(f)
    n = 0
    for fn, info in grid.items():
        key = os.path.splitext(fn)[0]
        w, h = info["w"], info["h"]
        if (w, h) == DEFAULT_TILE:
            continue   # 16x16 走默认
        # 不要覆盖显式声明的特效/字体/水面
        if key in TILE_OVERRIDES and TILE_OVERRIDES[key] != DEFAULT_TILE:
            continue
        TILE_OVERRIDES[key] = (w, h)
        n += 1
    return n

# 手环档位预设: (目标 tile 边长, 调色板颜色数)
# 颜色数权衡: 32 色对 7042 色压缩 220x, 偏色明显; 48~64 色基本保真, 体积只多 ~30%
PRESETS = {
    # 8px: 原尺寸的 1/2, NEAREST/BOX 精确 2:1 降采样, 体积最小, 手环 9 上 24 列视野
    "band-lite": {"tile": 8, "colors": 24},
    # 12px: 推荐档, 手环 9(192px) 上 16 列 x 40 行, 手环 10(212px) 上 17 列
    "band": {"tile": 12, "colors": 48},
    # 16px: 不降分辨率, 仅减色 + 重打包, 适用于手环 8/9 Pro (336px 宽)
    "band-pro": {"tile": 16, "colors": 64},
}

# 颜色配额倍率 (相对档位基准色数)
# 这些图集色调分散 (每个 buff/徽章一种独立色相), median-cut 在均分色数下误差明显偏高:
#   buffs 误差 38 / large_buffs 36 / badges 29 —— 而 tiles0 虽有 1018 色但集中在灰棕渐变, 48 色就够
# 用倍率而非绝对值, 这样 band-lite 档也按比例提升, 不改变档位间的相对定位
COLOR_BONUS = {
    "buffs": 2.5,
    "large_buffs": 2.5,
    "badges": 2.0,
    "items": 1.5,
    "amulet": 1.5,
    "ghost": 1.5,
    "icons": 1.3,
    "spell_icons": 1.3,
}


def colors_for(name: str, base: int) -> int:
    """图集实际可用的调色板色数 (上限 255, PNG-8 索引上限)"""
    return min(255, max(1, int(round(base * COLOR_BONUS.get(name, 1.0)))))

RESAMPLES = {
    "box": Image.BOX,
    "nearest": Image.NEAREST,
    "bilinear": Image.BILINEAR,
    "lanczos": Image.LANCZOS,
}


# --------------------------------------------------------------------------- #
# 2. 图像处理原语
# --------------------------------------------------------------------------- #

def split_sheet(img: Image.Image, tw: int, th: int, name: str = ""):
    """
    把精灵表切成 tile 列表, 返回 [(row, col, Image RGBA), ...]

    与游戏内 TextureFilm 行为一致: 列/行数用整除, 边缘不足一格的余量像素丢弃。
    (例: bat.png 128x16 按 15x15 网格 -> 8 列 x 1 行, 右侧 8px 忽略。
     早期版本要求整除, 在这类图集上直接抛错, 是把"假设"当成"约束"的典型 bug。)
    """
    w, h = img.size
    if w < tw or h < th:
        raise ValueError(
            f"精灵表{' ' + name if name else ''} 尺寸 {w}x{h} 小于网格 {tw}x{th}")
    out = []
    for r in range(h // th):
        for c in range(w // tw):
            out.append((r, c, img.crop((c * tw, r * th, (c + 1) * tw, (r + 1) * th))))
    return out


def scale_sheet(img: Image.Image, factor: float, resample):
    """
    alpha 预乘缩放: 先 RGB *= A/255 再缩放, 缩放后反解回 RGB。
    不做预乘的话, 透明像素的 RGB(通常是黑色) 会在缩放时渗进不透明边缘, 产生黑边。
    """
    if abs(factor - 1.0) < 1e-6:
        return img
    w, h = img.size
    dw, dh = max(1, int(round(w * factor))), max(1, int(round(h * factor)))
    if (dw, dh) == (w, h):
        return img

    arr = np.asarray(img, dtype=np.float32)
    a = arr[..., 3:4] / 255.0
    pre = np.concatenate([arr[..., :3] * a, arr[..., 3:4]], axis=-1)
    small = Image.fromarray(pre.astype(np.uint8), "RGBA").resize((dw, dh), resample)
    out = np.asarray(small, dtype=np.float32)
    oa = out[..., 3:4]
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(oa > 0, out[..., :3] * 255.0 / np.maximum(oa, 1.0), 0.0)
    res = np.concatenate([np.clip(rgb, 0, 255), oa], axis=-1).astype(np.uint8)
    return Image.fromarray(res, "RGBA")


def binarize_alpha(img: Image.Image, threshold: int) -> Image.Image:
    """alpha 二值化: 抠掉抗锯齿半透明像素, 让边缘重新变硬, PNG 也更好压。"""
    arr = np.asarray(img).copy()
    arr[..., 3] = np.where(arr[..., 3] >= threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def build_palette(tiles_rgba, n_colors: int):
    """
    从所有 tile 的不透明像素里做 median-cut 量化, 得到全局调色板。
    透明像素不参与训练(它们单独占索引 0), 否则调色板会被大片透明区背景色吃掉。
    """
    chunks = []
    for t in tiles_rgba:
        a = t[..., 3]
        rgb = t[..., :3][a >= 128]
        if rgb.size:
            chunks.append(rgb)
    if not chunks:
        raise RuntimeError("没有可用于训练调色板的不透明像素")
    samples = np.concatenate(chunks, axis=0)

    # 先去重, 避免大量重复颜色把 median-cut 的桶占满
    uniq = np.unique(samples.reshape(-1, 3), axis=0)
    side = math.ceil(math.sqrt(len(uniq)))
    flat = np.zeros((side * side, 3), dtype=np.uint8)
    flat[: len(uniq)] = uniq
    if len(uniq) < side * side:  # 尾部填充, 对调色板影响可忽略
        flat[len(uniq):] = uniq[: side * side - len(uniq)]
    train = Image.fromarray(flat.reshape(side, side, 3), "RGB")

    n = min(n_colors, len(uniq))
    pal_img = train.quantize(colors=n, method=Image.MEDIANCUT, dither=Image.NONE)
    raw = pal_img.getpalette()[: n * 3]
    pal = np.array(raw, dtype=np.uint8).reshape(-1, 3)
    return pal


def map_to_palette(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
    """把 (N,3) 的 RGB 映射到调色板下标, 用唯一色查表避免 O(N*K) 的距离矩阵。"""
    uniq, inv = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    idx_u = np.empty(len(uniq), dtype=np.int32)
    block = 4096
    for s in range(0, len(uniq), block):
        u = uniq[s: s + block].astype(np.int32)
        d = ((u[:, None, :] - pal[None, :, :].astype(np.int32)) ** 2).sum(axis=2)
        idx_u[s: s + block] = d.argmin(axis=1)
    return idx_u[inv].reshape(rgb.shape[:2])


# --------------------------------------------------------------------------- #
# 3. 主流程
# --------------------------------------------------------------------------- #

def collect_tiles(src_dir, target_tile, resample, alpha_threshold):
    """
    遍历源目录: 缩放 -> 二值化 -> 切 tile, 返回
        sheets: {name: {"tiles": [ndarray RGBA...], "meta": {...}}}

    双阈值策略 (针对低 alpha 内容):
      alpha < 阈值 像素判定: 标准阈值 (默认 128)
      判空判定:    缩放后的"原 alpha >= 32" 像素数 >= 6 (过滤纯噪点)
      若被判定为"非空"但标准 binarize 后变全透明 -> 改用低阈值 (max(32, threshold/4))
                   的 binarize 版本, 救回真实内容 (典型例子: piranha.png 第 0/1 格
                   alpha max=76, 是食人鱼水下半透明阴影, 旧管线会整个丢弃)。
    """
    sheets = OrderedDict()
    files = sorted(f for f in os.listdir(src_dir) if f.lower().endswith(".png"))
    low_threshold = max(32, alpha_threshold // 4)

    for fn in files:
        key = os.path.splitext(fn)[0]
        src = Image.open(os.path.join(src_dir, fn))
        has_alpha = src.mode in ("RGBA", "LA") or "transparency" in src.info
        img = src.convert("RGBA")
        if not has_alpha:  # 无 alpha 的图(水面、电弧)补成全不透明
            arr = np.asarray(img).copy()
            arr[..., 3] = 255
            img = Image.fromarray(arr, "RGBA")

        stw, sth = TILE_OVERRIDES.get(key, DEFAULT_TILE)
        # 目标 tile 边长; 对小尺寸源(如 4x4 阴影)只缩不放
        dst_tw = max(1, min(stw, target_tile))
        dst_th = max(1, min(sth, target_tile))
        factor = min(1.0, dst_tw / stw, dst_th / sth)

        scaled = scale_sheet(img, factor, resample)
        # 双 binarize: 标准版保持硬边像素画, 低阈值版救回浅色残影
        b_std = binarize_alpha(scaled, alpha_threshold)
        b_low = binarize_alpha(scaled, low_threshold)

        # 缩放后实际网格尺寸 (可能因取整而微调)
        gw, gh = b_std.size
        real_tw = max(1, int(round(stw * factor)))
        real_th = max(1, int(round(sth * factor)))
        cols, rows = gw // real_tw, gh // real_th

        # 切 scaled (未 binarize) 用于"非空判据"
        scaled_pre = np.asarray(scaled)

        tiles, metas = [], []
        for r, c, tile_std in split_sheet(b_std, real_tw, real_th, key):
            i = r * cols + c
            # 看原图 (binarize 之前) 这个格子的"真实内容"
            sub = scaled_pre[r * real_th:(r + 1) * real_th,
                             c * real_tw:(c + 1) * real_tw]
            n_content = int((sub[..., 3] >= 32).sum())
            empty = n_content < 6

            if empty or np.asarray(tile_std)[..., 3].max() > 0:
                arr = np.asarray(tile_std)
            else:
                # 标准 binarize 变全空, 用低阈值版救回
                tile_low = b_low.crop((c * real_tw, r * real_th,
                                       (c + 1) * real_tw, (r + 1) * real_th))
                arr = np.asarray(tile_low)
            tiles.append(arr)
            metas.append({"row": r, "col": c, "index": i,
                          "empty": empty, "nContentPx": n_content})

        sheets[key] = {
            "tiles": tiles,
            "metas": metas,
            "grid": {"cols": cols, "rows": rows},
            "tileSize": [real_tw, real_th],
            "srcSize": list(img.size),
            "srcTile": [stw, sth],
            "hasAlpha": bool(has_alpha),
        }
    return sheets


def pack_sheet(tiles, metas, tw, th, max_width):
    """
    剔除全透明 tile + 内容去重, 然后紧凑排列。
    "是否为空" 用 collect_tiles 阶段算好的 empty 标志 (基于缩放后原 alpha),
    而不是 binarize 后的 alpha —— 因为低 alpha 残影被低阈值 binarize 救回后,
    binarize 结果是全不透明, 不能用作"空"判据。
    返回 (canvas ndarray RGBA, placements, unique_count, dropped_count)
    """
    cols = max(1, max_width // tw)
    uniq_map = {}          # 内容指纹 -> 槽位序号
    slots = []             # 槽位 -> tile 数据
    placements = []        # 与 metas 一一对应: 槽位序号 or None
    dropped = 0

    for arr, meta in zip(tiles, metas):
        if meta.get("empty"):
            placements.append(None)
            dropped += 1
            continue
        fp = arr.tobytes()
        slot = uniq_map.get(fp)
        if slot is None:
            slot = len(slots)
            uniq_map[fp] = slot
            slots.append(arr)
        placements.append(slot)

    n = len(slots)
    if n == 0:
        return None, placements, 0, dropped
    use_cols = min(cols, n)
    use_rows = math.ceil(n / use_cols)
    canvas = np.zeros((use_rows * th, use_cols * tw, 4), dtype=np.uint8)
    for i, arr in enumerate(slots):
        r, c = divmod(i, use_cols)
        canvas[r * th: (r + 1) * th, c * tw: (c + 1) * tw] = arr
    return canvas, placements, n, dropped


def save_indexed(canvas: np.ndarray, pal: np.ndarray, path: str):
    """输出 PNG-8: 索引色 + tRNS(索引 0 全透明)。"""
    rgb = canvas[..., :3]
    a = canvas[..., 3]
    idx = map_to_palette(rgb, pal) + 1      # 0 号留给透明
    idx[a == 0] = 0
    im = Image.fromarray(idx.astype(np.uint8), "P")

    # 调色板只写实际用到的项: [透明占位, 真实颜色...]
    # 写满 256 项的话 PLTE 就占 768 字节, 小图集反而比原图还大
    full = np.zeros((len(pal) + 1, 3), dtype=np.uint8)
    full[1:] = pal
    im.putpalette(full.tobytes())
    im.info["transparency"] = 0
    im.save(path, optimize=True)
    return im


def save_rgba(canvas: np.ndarray, pal: np.ndarray, path: str):
    """输出 RGBA32: 仍走调色板量化(颜色数受限), 但保留 32 位像素格式, 兼容性最好。"""
    rgb = canvas[..., :3]
    a = canvas[..., 3]
    idx = map_to_palette(rgb, pal)
    quant = pal[idx]
    out = np.zeros(canvas.shape, dtype=np.uint8)
    out[..., :3] = quant
    out[..., 3] = a
    Image.fromarray(out, "RGBA").save(path, optimize=True)


def run_preset(src_dir, out_dir, preset, tile, colors, resample, alpha_threshold,
               max_width, png_mode, gen_js, palette_scope):
    os.makedirs(out_dir, exist_ok=True)
    sheets = collect_tiles(src_dir, tile, RESAMPLES[resample], alpha_threshold)

    if palette_scope == "global":
        all_tiles = [t for s in sheets.values() for t in s["tiles"]]
        global_pal = build_palette(all_tiles, colors)

    index = {
        "preset": preset,
        "targetTileSize": tile,
        "paletteColors": colors,
        "paletteScope": palette_scope,
        "resample": resample,
        "alphaThreshold": alpha_threshold,
        "pngMode": png_mode,
        "source": {
            "repo": "https://github.com/watabou/pixel-dungeon",
            "commit": "ca458a2 (v1.9.1)",
            "license": "GPL-3.0",
        },
        "targets": {
            "xiaomi-band-9": "192x490 pill-shaped",
            "xiaomi-band-10": "212x520 pill-shaped",
            "xiaomi-band-8-pro": "336x480 rectangle",
            "xiaomi-band-9-pro": "336x480 rectangle",
        },
        "sheets": {},
    }

    stat_rows = []
    sheet_pals = {}          # 每个精灵表自己的调色板, 供 palette.json 分组导出
    for name, s in sheets.items():
        tw, th = s["tileSize"]
        canvas, placements, n_uniq, n_drop = pack_sheet(
            s["tiles"], s["metas"], tw, th, max_width)

        # tiles 用紧凑数组: coords[i] = [x,y] 或 null(空 tile), i 即原生 tile 索引
        # 用对象字典的话 2000+ tile 的 manifest 能到 147KB, 比贴图本身还大
        #
        # 全空图集 (canvas is None) 必须先判再取 shape —— 旧代码把判空写在取 shape
        # 之后, 一旦某图集所有 tile 都被判空就会 AttributeError。这类图集在修正
        # 网格后确实会出现 (例如 exp_bar/shadow 这种只有 1~2 格的异形图)。
        sheet_info = {
            "image": f"{name}.png" if canvas is not None else None,
            "imageWidth": int(canvas.shape[1]) if canvas is not None else 0,
            "imageHeight": int(canvas.shape[0]) if canvas is not None else 0,
            "tileWidth": tw,
            "tileHeight": th,
            "sourceSize": s["srcSize"],
            "sourceTile": s["srcTile"],
            "grid": s["grid"],
            "tileCount": len(s["metas"]),
            "packedCount": n_uniq,
            "droppedEmpty": n_drop,
            "coords": [],
        }

        if canvas is None:
            index["sheets"][name] = sheet_info
            stat_rows.append((name, 0, 0, 0, 0, 0))
            continue

        # 调色板: global 模式全库共享, sheet 模式每个精灵表独立(避免被 banners 暖色吃掉)
        pal = global_pal if palette_scope == "global" \
            else build_palette(s["tiles"], colors_for(name, colors))
        sheet_pals[name] = pal

        if png_mode in ("indexed", "both"):
            out_png = os.path.join(out_dir, f"{name}.png")
            save_indexed(canvas, pal, out_png)
        if png_mode in ("rgba", "both"):
            out_png = os.path.join(out_dir, f"{name}.rgba.png")
            save_rgba(canvas, pal, out_png)

        use_cols = max(1, canvas.shape[1] // tw)
        src_path = os.path.join(src_dir, f"{name}.png")
        src_kb = os.path.getsize(src_path) / 1024
        dst_kb = os.path.getsize(os.path.join(out_dir, f"{name}.png")) / 1024 \
            if png_mode in ("indexed", "both") else \
            os.path.getsize(os.path.join(out_dir, f"{name}.rgba.png")) / 1024

        for slot in placements:
            if slot is None:
                sheet_info["coords"].append(None)
            else:
                r, c = divmod(slot, use_cols)
                sheet_info["coords"].append([c * tw, r * th])
        index["sheets"][name] = sheet_info
        stat_rows.append((name, s["grid"]["cols"] * s["grid"]["rows"],
                          n_uniq, n_drop, src_kb, dst_kb))

    with open(os.path.join(out_dir, "sprites.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    if gen_js:
        js = ["// 自动生成, 请勿手改。生成命令见 tools/convert_sprites.py",
              f"export const PRESET = '{preset}'",
              f"export const TILE = {tile}"]
        # 只导出坐标, 保持文件精简
        compact = {}
        for name, sinfo in index["sheets"].items():
            if sinfo.get("image") is None:
                continue
            compact[name] = {
                "image": sinfo["image"],
                "iw": sinfo["imageWidth"], "ih": sinfo["imageHeight"],
                "tw": sinfo["tileWidth"], "th": sinfo["tileHeight"],
                "cols": sinfo["grid"]["cols"],
                "c": sinfo["coords"],
            }
        js.append("export const SHEETS = " + json.dumps(compact, separators=(",", ":")))
        js.append(
            "export function tile(sheet, i) {\n"
            "  const s = SHEETS[sheet]\n"
            "  if (!s) return null\n"
            "  const p = s.c[i]\n"
            "  return p ? { x: p[0], y: p[1], w: s.tw, h: s.th } : null\n"
            "}\n"
            "// CSS 用法: background-image: url(图集); background-position: -x px -y px;\n"
            "//           并把 background-size 设为图集原始尺寸, 配合 width/height 为 tile 尺寸使用"
        )
        with open(os.path.join(out_dir, "sprites.js"), "w", encoding="utf-8") as f:
            f.write("\n".join(js) + "\n")

    # 调色板单独导出, 便于做主题换色
    # sheet 模式按精灵表分组导出; 之前只写了最后一张图的 pal, 导致 palette.json 不完整
    def hexes(p):
        return ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in p]

    if palette_scope == "global":
        payload = {"scope": "global", "colors": hexes(global_pal)}
    else:
        payload = {"scope": "sheet", "colors": {k: hexes(v) for k, v in sheet_pals.items()}}
    with open(os.path.join(out_dir, "palette.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=0)

    return stat_rows


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    n_grid = _load_sprite_grid()
    if n_grid:
        print(f"[grid] 从 sprite_grid.json 注入了 {n_grid} 张非 16x16 游戏网格")
    ap = argparse.ArgumentParser(description="Pixel Dungeon 素材 -> 小米手环快应用低精度贴图")
    ap.add_argument("--src", default=os.path.join(root, "src-assets", "orig"))
    ap.add_argument("--out", default=os.path.join(root, "output"))
    ap.add_argument("--preset", default="band,band-lite",
                    help="逗号分隔的档位名, 或 custom 配合 --tile/--colors")
    ap.add_argument("--tile", type=int, default=None, help="目标 tile 边长(覆盖 preset)")
    ap.add_argument("--colors", type=int, default=None, help="调色板颜色数(覆盖 preset)")
    ap.add_argument("--resample", default="box", choices=list(RESAMPLES))
    ap.add_argument("--alpha-threshold", type=int, default=128)
    ap.add_argument("--max-width", type=int, default=256, help="图集最大宽度(px)")
    ap.add_argument("--png-mode", default="indexed", choices=["indexed", "rgba", "both"])
    ap.add_argument("--palette-scope", default="sheet", choices=["sheet", "global"],
                    help="调色板作用域: sheet=每图集独立(默认, 颜色保真) global=全库共享")
    ap.add_argument("--no-js", action="store_true", help="不生成 sprites.js")
    args = ap.parse_args()

    presets = [p.strip() for p in args.preset.split(",") if p.strip()]
    grand_total_src = sum(os.path.getsize(os.path.join(args.src, f))
                          for f in os.listdir(args.src) if f.endswith(".png"))

    print(f"源素材: {args.src}  ({grand_total_src/1024:.1f} KB)")
    print("=" * 108)

    for p in presets:
        cfg = PRESETS.get(p, {"tile": 12, "colors": 32})
        tile = args.tile or cfg["tile"]
        colors = args.colors or cfg["colors"]
        out_dir = os.path.join(args.out, p)
        print(f"\n>>> 档位 {p}:  tile={tile}px  调色板={colors}色  "
              f"重采样={args.resample}  输出={out_dir}")
        print("-" * 108)
        rows = run_preset(args.src, out_dir, p, tile, colors, args.resample,
                          args.alpha_threshold, args.max_width, args.png_mode,
                          not args.no_js, args.palette_scope)
        print(f"{'精灵表':<20}{'原tile':>8}{'去重后':>8}{'空剔':>7}"
              f"{'原KB':>9}{'新KB':>9}{'压缩比':>9}")
        t_src = t_dst = 0
        for name, n_tile, n_uniq, n_drop, src_kb, dst_kb in rows:
            t_src += src_kb
            t_dst += dst_kb
            ratio = f"{src_kb/dst_kb:.1f}x" if dst_kb > 0 else "-"
            print(f"{name:<20}{n_tile:>8}{n_uniq:>8}{n_drop:>7}"
                  f"{src_kb:>9.1f}{dst_kb:>9.1f}{ratio:>9}")
        print("-" * 108)
        print(f"{'合计':<20}{'':>8}{'':>8}{'':>7}{t_src:>9.1f}{t_dst:>9.1f}"
              f"{t_src/t_dst if t_dst else 0:>8.1f}x")

        summary = {
            "preset": p, "tile": tile, "colors": colors,
            "sourceTotalKB": round(t_src, 1), "outputTotalKB": round(t_dst, 1),
            "compression": round(t_src / t_dst, 2) if t_dst else None,
        }
        with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n完成。")


if __name__ == "__main__":
    sys.exit(main())
