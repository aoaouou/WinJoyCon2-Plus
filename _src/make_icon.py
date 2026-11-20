# -*- coding: utf-8 -*-
"""生成 WinJoyCon2-Plus 应用图标。

设计参考 Ryujinx 的构图语言（深色圆角方块 + 两支手柄），但完全重画：
  · 左手柄 = Joy-Con 2（主泡泡糖粉 #ff6fae），机身刻数字 2
  · 右手柄 = Joy-Con 1（浅粉 #ffa8ce），机身刻数字 1
  · 中间白色箭头表达 2 → 1 的转换
  · 保留真实 Joy-Con 形态：圆角长条、顶部滑轨条、摇杆（实心+高光）、四键菱形
  · 主题色与 theme.py 一致：粉 #ff6fae / 深 #e04a8f / 浅 #ffd0e4 / 文字 #5c2340

用法：
    python make_icon.py
输出（写到脚本所在目录）：
    logo_256.ico   多尺寸 16~256
    logo_256.png   256x256

调整建议：
  · 改主色 → PINK / PINK_LIGHT
  · 改手柄粗细 → jw / jh（build 内）
  · 改倾角 → rotate 的 12 / -14 度
  · 改数字字号 → make_joycon 内 fsize
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = Path(__file__).resolve().parent
SCALE = 4                 # 4x 超采样后缩回，保证边缘平滑
S = 256 * SCALE

# ── 主题色（与 theme.py 一致）────────────────────────────
BG_DARK = (58, 24, 42)        # 深梅紫底
PINK = (255, 111, 174)        # 主泡泡糖粉 #ff6fae
PINK_LIGHT = (255, 168, 206)  # 浅粉 #ffa8ce
PINK_SOFT = (255, 208, 228)   # 极浅粉 #ffd0e4
WHITE = (255, 255, 255)


def find_font(size: int):
    """找可用粗体字体画世代数字。"""
    for c in (r"C:\Windows\Fonts\arialbd.ttf",
              r"C:\Windows\Fonts\segoeuib.ttf",
              r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\impact.ttf"):
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_joycon(w: int, h: int, body, btn_color, number: int, num_color):
    """生成一支 Joy-Con 图层（未旋转，四周留 pad 供旋转抗锯齿）。"""
    pad = int(w * 0.06)
    W, H = w + pad * 2, h + pad * 2
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # 机身
    rad = int(w * 0.47)
    d.rounded_rectangle([pad, pad, pad + w - 1, pad + h - 1],
                        radius=rad, fill=body)

    # 顶部滑轨条（SL/SR 侧），限制在圆角内侧不溢出
    rail_h = int(h * 0.035)
    d.rounded_rectangle(
        [pad + int(w * 0.26), pad + int(h * 0.028),
         pad + int(w * 0.74), pad + int(h * 0.028) + rail_h],
        radius=rail_h // 2, fill=btn_color)

    # 摇杆：实心圆 + 内高光环（更像真实摇杆）
    sr = int(w * 0.25)
    scx, scy = pad + w // 2, pad + int(h * 0.30)
    d.ellipse([scx - sr, scy - sr, scx + sr, scy + sr], fill=btn_color)
    nr = int(sr * 0.46)
    d.ellipse([scx - nr, scy - nr, scx + nr, scy + nr],
              fill=tuple(min(255, int(c * 1.18)) for c in btn_color))

    # 四颗按键（菱形）
    br = max(2, int(w * 0.070))
    bx, by = pad + w // 2, pad + int(h * 0.565)
    gap = int(w * 0.20)
    for dx, dy in ((0, -gap), (0, gap), (-gap, 0), (gap, 0)):
        d.ellipse([bx + dx - br, by + dy - br, bx + dx + br, by + dy + br],
                  fill=btn_color)

    # 世代数字（2 / 1），压在机身下部
    f = find_font(int(w * 0.44))
    txt = str(number)
    tb = d.textbbox((0, 0), txt, font=f)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text((pad + w // 2 - tw // 2 - tb[0],
            pad + int(h * 0.80) - th // 2 - tb[1]),
           txt, font=f, fill=num_color)
    return layer


def build() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 深梅紫圆角底
    pad = int(S * 0.045)
    box = [pad, pad, S - 1 - pad, S - 1 - pad]
    radius = int(S * 0.22)
    d.rounded_rectangle(box, radius=radius, fill=BG_DARK)

    # 中心柔光（避免死板）
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gr = int(S * 0.40)
    ImageDraw.Draw(glow).ellipse(
        [S // 2 - gr, S // 2 - gr, S // 2 + gr, S // 2 + gr],
        fill=(PINK[0], PINK[1], PINK[2], 22))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    img.paste(Image.alpha_composite(img, glow), (0, 0), mask)

    jw, jh = int(S * 0.185), int(S * 0.50)

    # 左 = JC2（主粉，浅色按键/数字深色）
    left = make_joycon(jw, jh, PINK, PINK_SOFT, 2, BG_DARK).rotate(
        12, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(left, (int(S * 0.30) - left.width // 2,
                               int(S * 0.50) - left.height // 2))

    # 右 = JC1（浅粉，深色按键/数字深色）
    right = make_joycon(jw, jh, PINK_LIGHT, BG_DARK, 1, BG_DARK).rotate(
        -14, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(right, (int(S * 0.70) - right.width // 2,
                                int(S * 0.50) - right.height // 2))

    # 中间转换箭头（2 → 1）
    acx, acy = S // 2, int(S * 0.50)
    aw, ah = int(S * 0.085), int(S * 0.048)
    d.rounded_rectangle([acx - aw // 2, acy - ah // 4,
                         acx + aw // 3, acy + ah // 4],
                        radius=ah // 4, fill=WHITE)
    d.polygon([(acx + aw // 3, acy - ah), (acx + aw // 3 + ah, acy),
               (acx + aw // 3, acy + ah)], fill=WHITE)
    return img


def main() -> None:
    big = build()
    base = big.resize((256, 256), Image.LANCZOS)
    base.save(OUT_DIR / "logo_256.ico",
              sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    base.save(OUT_DIR / "logo_256.png")
    print("已生成:", OUT_DIR / "logo_256.ico")
    print("已生成:", OUT_DIR / "logo_256.png")


if __name__ == "__main__":
    main()
