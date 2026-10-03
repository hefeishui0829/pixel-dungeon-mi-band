# `band/` — 12px · 48 色 · 推荐档

适用于**小米手环 9 / 10**（192×490 / 212×520 胶囊屏）。是体积和画质的最佳平衡点。

## 参数（来自 `report.json`）

| 项 | 值 |
|---|---|
| tile 边长 | **12 px**（原图 16px 的 3/4） |
| 调色板 | **48 色 / sheet**（按图集独立量化，保真度优先） |
| 重采样 | box + alpha 预乘（避免透明黑边） |
| 源 PNG 总体积 | 465.4 KB（82 张） |
| **本档总体积** | **84.4 KB**（82 张 PNG） |
| **压缩比** | **5.5×** |
| 解码后 RGBA 显存 | ≈ 1181 KB（≈ 2.3× 节省） |

## 在手环上能看多远

| 屏幕 | 一屏 tile 数 |
|---|---|
| 手环 9（192 物理像素宽） | **16 列 × 40 行 = 640 块** |
| 手环 10（212 物理像素宽） | 17 列 × 43 行 |

## 文件清单

```
band/
├── *.png                ← 82 张 PNG-8 索引色精灵表 (≤4KB / 张)
├── sprites.json         ← 完整 manifest (coords: [x,y] 数组, 与原版 tile 编号一致)
├── sprites.js           ← JS 模块, 直接 import
├── palette.json         ← 调色板 (调试用)
└── report.json          ← 本档统计 (上面表格的数据来源)
```

代表 sprite 实测：

| 精灵表 | 图集尺寸 | tile 数 | 空 tile |
|---|---|---|---|
| `tiles0` | 252×36 | 64 | 1 |
| `warrior` | 252×72 | 128 | 16 |
| `items` | 252×72 | 128 | 2 |

> 空 tile 在 `coords` 数组里标记为 `null`，调用 `tile(name, i)` 时返回 `null`。

## 用法

### 喂给快应用 demo

```bash
bash ../demo/tools/prepare_demo.sh band    # 把本档拷到 demo/src/common/
```

### 在自己的 `.ux` 里直接 import

```js
import { SHEETS, TILE, tile } from '../common/sprites.js'

const s = SHEETS['tiles0']
// → { image: "tiles0.png", iw: 252, ih: 36, tw: 12, th: 12, cols: 7, c: [...] }

const p = tile('tiles0', 42)  // → { x, y, w, h } 或 null(空 tile)
```

配套 CSS：

```css
.tile {
  background-image: url('/common/tiles0.png');
  background-position: -${p.x}px -${p.y}px;
  background-size: ${s.iw}px ${s.ih}px;
  width: ${s.tw}px; height: ${s.th}px;
}
```

## 重新生成本档

```bash
python3 ../../tools/convert_sprites.py --preset band
```
