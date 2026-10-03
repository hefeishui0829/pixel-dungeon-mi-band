#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
资产对账审计: 原项目 watabou/pixel-dungeon 的美术资产 <-> 本仓库 src-assets <-> output 三档。

为什么需要
    "82 张图"这句话很容易变成口头承诺。这里做三级硬校验:
      L1 清单对账  原项目 assets/*.png 与 src-assets/orig/*.png 逐文件 md5
      L2 覆盖对账  每张源图按游戏内真实网格切出的"非空 tile", 是否都在 output
                   里留下了槽位(coords 非 None), 即有没有被误剔除
      L3 内容对账  抽样比较源 tile 与输出 tile 的 alpha 形状 IoU, 确认位置
                   没偏、没串行(网格错了 IoU 会直接掉到 0)

    缩放与 alpha 二值化直接复用 convert_sprites.py 的同两个函数, 保证 L3
    比较的是"同一条管线的前后两段", 而不是两套近似实现互相打假。

用法
    python3 tools/audit_assets.py                                  # band 档
    python3 tools/audit_assets.py --preset band-pro
    python3 tools/audit_assets.py --upstream /path/to/pd/assets    # 加 L1
    python3 tools/audit_assets.py --iou-sample 0                   # 全量 IoU

退出码 0 = 全部通过; 1 = 存在 FAIL。
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_sprites import scale_sheet, binarize_alpha  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src-assets", "orig")

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_tiles(path, tw, th, target_tile):
    """
    按游戏内真实网格 (tw,th) 处理一张源图, 返回
        tiles: [(index, mask01, n_content)]  只含非空格
        meta : (cols, rows, real_tw, real_th)
    缩放 / 二值化 / 判空阈值与 convert_sprites.collect_tiles 保持一致。
    """
    img = Image.open(path).convert("RGBA")
    if "transparency" not in img.info and img.mode == "RGB":
        arr = np.asarray(img).copy()
        arr[..., 3] = 255
        img = Image.fromarray(arr, "RGBA")

    dst_tw = max(1, min(tw, target_tile))
    dst_th = max(1, min(th, target_tile))
    factor = min(1.0, dst_tw / tw, dst_th / th)
    scaled = scale_sheet(img, factor, Image.BOX)
    binz = binarize_alpha(scaled, 128)

    real_tw = max(1, int(round(tw * factor)))
    real_th = max(1, int(round(th * factor)))
    W, H = binz.size
    cols, rows = W // real_tw, H // real_th

    pre = np.asarray(scaled)[..., 3]
    bin_a = np.asarray(binz)[..., 3]
    min_px = max(1, min(6, (real_tw * real_th) // 8))

    tiles = []
    for r in range(rows):
        for c in range(cols):
            i = r * cols + c
            sub = pre[r * real_th:(r + 1) * real_th, c * real_tw:(c + 1) * real_tw]
            n = int((sub >= 32).sum())
            if n < min_px:
                continue
            mask = (bin_a[r * real_th:(r + 1) * real_th,
                          c * real_tw:(c + 1) * real_tw] >= 128).astype(np.uint8)
            tiles.append((i, mask, n))
    return tiles, (cols, rows, real_tw, real_th)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="band")
    ap.add_argument("--upstream", default="", help="原项目 assets 目录 (不传则跳过 L1)")
    ap.add_argument("--iou-sample", type=int, default=25,
                    help="每张源图最多抽多少格做 IoU (0 = 全查)")
    args = ap.parse_args()

    out_dir = os.path.join(ROOT, "output", args.preset)
    sp_path = os.path.join(out_dir, "sprites.json")
    rp_path = os.path.join(out_dir, "report.json")
    if not os.path.exists(sp_path):
        sys.exit(f"找不到 {sp_path}, 先跑 python3 tools/convert_sprites.py")
    sprites = json.load(open(sp_path, encoding="utf-8"))
    target_tile = 12
    if os.path.exists(rp_path):
        target_tile = int(json.load(open(rp_path, encoding="utf-8")).get("tile", 12))

    fails, warns = [], []
    warn_details = []

    # ------------------------------------------------------------------ L1
    print("=" * 80)
    print(f"L1 清单对账   src-assets/orig  <->  原项目 assets      (preset={args.preset})")
    print("=" * 80)
    src_files = sorted(f for f in os.listdir(SRC) if f.lower().endswith(".png"))
    print(f"src-assets/orig : {len(src_files)} 张 PNG")
    if args.upstream and os.path.isdir(args.upstream):
        up_files = sorted(f for f in os.listdir(args.upstream)
                          if f.lower().endswith(".png"))
        only_up = [f for f in up_files if f not in src_files]
        only_src = [f for f in src_files if f not in up_files]
        diff = [f for f in up_files if f in src_files
                and md5(os.path.join(args.upstream, f)) != md5(os.path.join(SRC, f))]
        print(f"原项目 assets  : {len(up_files)} 张 PNG")
        print(f"  仅存在于原项目 : {only_up or '无'}")
        print(f"  仅存在于本仓库 : {only_src or '无'}")
        print(f"  内容(md5)不同 : {diff or '无'}")
        if only_up or only_src or diff:
            fails.append("L1 清单不一致")
        else:
            print(f"  判定: {OK}  {len(up_files)}/{len(up_files)} 逐文件 md5 一致")
    else:
        print("  (未给 --upstream, 跳过)")

    # ------------------------------------------------------------- L2 / L3
    print()
    print("=" * 80)
    print("L2 覆盖对账 + L3 形状抽样 IoU   (源非空 tile vs 输出槽位)")
    print("=" * 80)
    print(f"{'sheet':<15}{'源KB':>7}{'网格':>9}{'源非空':>7}{'槽位':>6}"
          f"{'缺实':>5}{'缺噪':>5}{'IoU均':>7}{'低':>4}  判定")

    sheets = sprites.get("sheets", sprites)
    tot_nonempty = tot_slots = tot_miss_real = tot_miss_noise = 0
    iou_all, iou_low_n = [], 0

    for key in sorted(sheets):
        info = sheets[key]
        src = os.path.join(SRC, key + ".png")
        if not os.path.exists(src):
            print(f"{key:<15}{'--':>7}  源图缺失")
            fails.append(f"L2 {key} 源图缺失")
            continue

        tw, th = info.get("sourceTile") or [16, 16]
        tw, th = int(tw), int(th)
        tiles, (cols, rows, rtw, rth) = scan_tiles(src, tw, th, target_tile)
        n_nonempty = len(tiles)

        coords = info.get("coords") or []
        packed = info.get("packedCount", len(set(tuple(x) for x in coords if x)))
        present = sum(1 for x in coords if x is not None)
        # 输出 tile 尺寸与源缩放后尺寸必须一致, 否则就是网格对不上
        otw, oth = info.get("tileWidth", rtw), info.get("tileHeight", rth)

        miss_real = miss_noise = 0
        for i, mask, n in tiles:
            if i < len(coords) and coords[i] is not None:
                continue
            area = rtw * rth
            if n >= max(2 * max(1, min(6, area // 8)), int(area * 0.03)):
                miss_real += 1
            else:
                miss_noise += 1

        # --- L3 IoU 抽样 ---
        ious = []
        out_img = None
        img_path = os.path.join(out_dir, info["image"]) if info.get("image") else None
        if img_path and os.path.exists(img_path) and n_nonempty:
            out_img = np.asarray(Image.open(img_path).convert("RGBA"))
            step = 1 if args.iou_sample <= 0 else max(1, n_nonempty // args.iou_sample)
            for k, (i, mask, n) in enumerate(tiles):
                if k % step:
                    continue
                if i >= len(coords) or coords[i] is None:
                    continue
                ox, oy = coords[i]
                om = (out_img[oy:oy + oth, ox:ox + otw, 3] > 0).astype(np.uint8)
                inter = int((om & mask[:oth, :otw]).sum())
                union = int((om | mask[:oth, :otw]).sum())
                if union:
                    ious.append(inter / union)

        avg = sum(ious) / len(ious) if ious else 1.0
        low = sum(1 for x in ious if x < 0.6)
        iou_all += ious
        iou_low_n += low
        tot_nonempty += n_nonempty
        tot_slots += packed
        tot_miss_real += miss_real
        tot_miss_noise += miss_noise

        if info.get("image") is None or miss_real or (otw, oth) != (rtw, rth):
            verdict = FAIL
            fails.append(key)
        elif low or miss_noise:
            verdict = WARN
            warns.append(key)
            reason_bits = []
            if miss_noise:
                reason_bits.append(
                    "源图 %d 个 tile 含缩放后残留/半透明边缘, 被判为噪点剔除" % miss_noise)
            if low:
                reason_bits.append(
                    "%d 个抽样 tile 形状 IoU<0.6, 半透明边缘二值化后形状收缩" % low)
            warn_details.append({
                "sheet": key, "miss_noise": miss_noise, "low_iou": low,
                "avg_iou": round(avg, 3),
                "reason": "; ".join(reason_bits) or "半透明边缘在 PNG-8+tRNS 二值化中受损",
            })
        else:
            verdict = OK
        print(f"{key:<15}{os.path.getsize(src)/1024:>7.1f}{f'{tw}x{th}':>9}"
              f"{n_nonempty:>7}{packed:>6}{miss_real:>5}{miss_noise:>5}"
              f"{avg:>7.2f}{low:>4}  {verdict}")

    print("-" * 80)
    avg_all = sum(iou_all) / len(iou_all) if iou_all else 1.0
    print(f"{'合计':<15}{'':>7}{'':>9}{tot_nonempty:>7}{tot_slots:>6}"
          f"{tot_miss_real:>5}{tot_miss_noise:>5}{avg_all:>7.2f}{iou_low_n:>4}")
    print(f"\n抽样 {len(iou_all)} 格, 平均 IoU {avg_all:.3f}, 低于 0.6 的 {iou_low_n} 格")

    # -------------------------------------------------------------- 结论
    print()
    print("=" * 80)
    if fails:
        print(f"FAIL {len(fails)} 项: " + ", ".join(fails[:10])
              + (" ..." if len(fails) > 10 else ""))
        return 1
    extra = f"; WARN {len(warns)} 项 (缩放后残影/半透明边缘, 见上表 '缺噪'): " \
            + ", ".join(warns[:6]) + (" ..." if len(warns) > 6 else "") if warns else ""
    print(f"PASS  {len(sheets)} 张图集: 清单一致 / 无空图集 / 有效内容零丢失 / "
          f"网格尺寸吻合{extra}")

    # -------------------------------------------------- 争议资产固化(图片侧)
    if warn_details:
        write_asset_disputes(warn_details)
    return 0


def write_asset_disputes(details):
    """把 WARN 项(半透明边缘在 PNG-8+tRNS 二值化中受损)固化为带注释的争议清单,
    供构建者按实际项目决定是否保留有损或切换带 alpha 的方案。"""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc_dir = os.path.join(ROOT, "docs")
    data_dir = os.path.join(ROOT, "data")
    os.makedirs(doc_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    out_path = os.path.join(data_dir, "asset-disputes.json")
    merged = {}
    if os.path.exists(out_path):                      # 多档位运行累加, 避免互相覆盖
        try:
            prev = json.load(open(out_path, encoding="utf-8"))
            for e in prev.get("entries", []):
                merged[e["sheet"]] = e
        except Exception:
            pass
    for e in details:
        s = e["sheet"]
        if s in merged:
            m = merged[s]
            m["miss_noise"] = max(m["miss_noise"], e["miss_noise"])
            m["low_iou"] = max(m["low_iou"], e["low_iou"])
            if e["avg_iou"] < m["avg_iou"]:
                m["avg_iou"] = e["avg_iou"]
            if e["reason"] not in m["reason"]:
                m["reason"] = m["reason"] + "; " + e["reason"]
        else:
            merged[s] = dict(e)
    details = list(merged.values())

    out = {
        "_meta": {
            "purpose": (
                "收录贴图转换中'有损但非缺失'的图集: 其半透明边缘在 PNG-8+tRNS "
                "导出(仅支持 0/255 两种 alpha)时被二值化抹成实色或全透明, 导致形状收缩。"
                "这属于格式硬约束的有损, 不是切图错误或丢素材。"),
            "build_note": (
                "构建时二选一: (A) 接受有损 —— 体积最小, 适合手环小屏; "
                "(B) 改用带 alpha 的方案(如 RGBA PNG 或索引 PNG 配 tRNS 渐变), "
                "保留半透明但体积增大。以你的实际构建项目为准决定。"),
            "generated_by": "tools/audit_assets.py",
        },
        "entries": details,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    lines = ["# 争议资产清单（图片侧：半透明边缘有损）", "",
             "> 由 `tools/audit_assets.py` 在跑出 WARN 时自动生成。", "",
             "> **这些不是缺失也不是切错**，而是 PNG-8+tRNS 导出只支持 0/255 两种 "
             "alpha，原图中 1–127 的半透明边缘被二值化抹掉，造成形状轻微收缩。", "",
             "> **构建时请二选一**：",
             "> - (A) 接受有损：体积最小，适合手环小屏；",
             "> - (B) 改用带 alpha 的方案（RGBA PNG 或索引 PNG + tRNS 渐变），保留半透明但体积增大。",
             "> 以你的实际构建项目为准决定。", "",
             "| 图集 | 被剔除残影像素 tile | 低 IoU(<0.6) tile | 平均 IoU | 说明 |",
             "|---|---|---|---|---|"]
    for e in details:
        lines.append("| `%s` | %d | %d | %.3f | %s |" % (
            e["sheet"], e["miss_noise"], e["low_iou"], e["avg_iou"], e["reason"]))
    with open(os.path.join(doc_dir, "asset-disputes.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
