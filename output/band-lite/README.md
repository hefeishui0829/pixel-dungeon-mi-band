# `band-lite/` — 8px · 24 色 · 极限档

体积最小，但**画质损失较大**（人物五官丢失、地牢纹理糊成一团）。仅在内存极紧张或老手环上推荐。

## 参数（来自 `report.json`）

| 项 | 值 |
|---|---|
| tile 边长 | **8 px**（原图 16px 的 1/2） |
| 调色板 | **24 色 / sheet** |
| 重采样 | box + alpha 预乘 |
| 源 PNG 总体积 | 465.4 KB |
| **本档总体积** | **45.6 KB**（最小） |
| **压缩比** | **10.2×** |
| 解码后 RGBA 显存 | ≈ 545 KB（≈ 5.1× 节省） |

## 在手环上能看多远

| 屏幕 | 一屏 tile 数 |
|---|---|
| 手环 9（192 物理像素宽） | **24 列 × 61 行 = 1464 块**（远视模式） |
| 手环 10 | 26 列 × 65 行 |

视野很大，但每块只有 8 个像素——**火焰、生命药水、人物脸这些细节识别困难**，建议把 UI 元素的字符也做特殊处理（用 emoji/纯几何）。

## 何时选它

- 老款手环（手环 7 等）的 RAM < 几 MB 时
- 你的游戏是「roguelike 但更抽象」风格（如 ASCII 风、地形用色块辨识）
- 已经做完整的人物放大/重绘，本目录只用来承担「地图瓦片」

否则默认用 `band/`（12px）。

## 文件结构

同 `band/`：82 张 PNG + `sprites.json` / `sprites.js` / `palette.json` / `report.json`。

## 用法

```bash
python3 ../../tools/convert_sprites.py --preset band,band-lite   # 同时生成两档
bash ../demo/tools/prepare_demo.sh band-lite                       # 拷到 demo
```
