"""The Agent Jo Jobs logo, rebuilt from the portrait.

    python tools/make_logo.py            (needs Pillow: pip install pillow)

Agent Jo's portrait in a green ring, with a green hexagon badge (the lattice's
cell, from symbolicsynapse.co.za) carrying a briefcase, so Jobs can be told
apart from Agent Jo at a glance: in the taskbar, on the desktop, in a browser
tab. Rendered by Chromium from one SVG at every size an icon needs; the small
sizes get a heavier ring and a bigger badge so they still read at 16-48 px.

Writes web_jobs/icons/*, web_phone/icon-*.png, agent-jo-jobs.ico and
branding/agent-jo-jobs-logo-1024.png. The portrait is branding/portrait-512.png.
"""
import base64, io, shutil, sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "branding" / "portrait-512.png"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "branding" / "build"
OUT.mkdir(parents=True, exist_ok=True)
portrait = "data:image/png;base64," + base64.b64encode(SRC.read_bytes()).decode()


def hexagon(cx, cy, r):
    k = 0.8660254
    pts = [(cx, cy - r), (cx + r * k, cy - r / 2), (cx + r * k, cy + r / 2),
           (cx, cy + r), (cx - r * k, cy + r / 2), (cx - r * k, cy - r / 2)]
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def svg(small: bool, badge: bool = True) -> str:
    R0 = 500                                # outer edge of the ring
    ring = 84 if small else 46
    gap = 26 if small else 18
    pr = R0 - ring - gap                    # the portrait's radius
    bx = by = 772 if small else 800         # badge centre
    br = 236 if small else 170              # badge radius
    out = 30 if small else 22               # the dark edge round the badge
    S = 980                                 # portrait drawn this big, face centred
    fx, fy = 0.51, 0.47                     # face a little up and left of the badge
    ix, iy = 512 - fx * S, 512 - fy * S
    sw = 3.2 if small else 2.2              # briefcase stroke, in its 24-unit grid
    gs = br * 1.02 / 12                     # glyph scale: 24 units across the badge
    gx, gy = bx - 12 * gs, by - 11.6 * gs
    glyph = (f'<g transform="translate({gx:.1f} {gy:.1f}) scale({gs:.3f})" fill="none" '
             f'stroke="#04200f" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">'
             '<rect x="3.5" y="7.5" width="17" height="12" rx="2.2"/>'
             '<path d="M8.5 7.5V5.6a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.9"/>'
             '<path d="M3.5 12.6h17"/></g>')
    badge_svg = ""
    if badge:
        badge_svg = (
            f'<polygon points="{hexagon(bx, by, br + out)}" fill="#03060B" '
            f'stroke="#03060B" stroke-width="{out * 0.9:.0f}" stroke-linejoin="round"/>'
            f'<polygon points="{hexagon(bx, by, br)}" fill="url(#mint)" '
            f'stroke="url(#mint)" stroke-width="{br * 0.16:.0f}" stroke-linejoin="round"/>'
            f'<polygon points="{hexagon(bx, by, br * 0.93)}" fill="none" '
            f'stroke="rgba(255,255,255,.35)" stroke-width="5" stroke-linejoin="round"/>'
            + glyph)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="100%" height="100%">
  <defs>
    <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#9ff0c9"/>
      <stop offset=".38" stop-color="#46d39a"/>
      <stop offset="1" stop-color="#178a5c"/>
    </linearGradient>
    <linearGradient id="mint" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#7fe9b8"/>
      <stop offset="1" stop-color="#2fae7b"/>
    </linearGradient>
    <clipPath id="face"><circle cx="512" cy="512" r="{pr}"/></clipPath>
  </defs>
  <circle cx="512" cy="512" r="{R0}" fill="url(#ring)"/>
  <circle cx="512" cy="512" r="{R0 - ring}" fill="#03060B"/>
  <image href="{portrait}" x="{ix:.1f}" y="{iy:.1f}" width="{S}" height="{S}"
         clip-path="url(#face)" preserveAspectRatio="xMidYMid slice"/>
  <circle cx="512" cy="512" r="{pr}" fill="none" stroke="rgba(70,211,154,.35)" stroke-width="3"/>
  {badge_svg}
</svg>'''


def render(pg, size, small, badge=True):
    pg.set_viewport_size({"width": size, "height": size})
    pg.set_content(f'<html><body style="margin:0;background:transparent">'
                   f'<div style="width:{size}px;height:{size}px">{svg(small, badge)}</div></body></html>')
    pg.wait_for_timeout(150)
    png = pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
    return Image.open(io.BytesIO(png)).convert("RGBA")


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    master = render(pg, 1024, small=False)
    master.save(OUT / "logo-1024.png")
    big = {}
    for s in (512, 384, 256, 192, 180, 128):
        # downscale the master: smoother than rasterising the photo small
        big[s] = master.resize((s, s), Image.LANCZOS)
        big[s].save(OUT / f"icon-{s}.png", optimize=True)
    small = {}
    for s in (16, 24, 32, 48, 64):
        small[s] = render(pg, s, small=True)
        small[s].save(OUT / f"small-{s}.png")
    # a maskable icon: full bleed, the logo inside the safe zone (80%)
    bg = Image.new("RGBA", (512, 512), (3, 6, 11, 255))
    inner = master.resize((400, 400), Image.LANCZOS)
    bg.alpha_composite(inner, (56, 56))
    bg.save(OUT / "maskable-512.png", optimize=True)
    b.close()

# the Windows icon: tuned small sizes, the master scaled for the large ones
order = [16, 24, 32, 48, 64, 128, 256]
imgs = {**{s: small[s] for s in (16, 24, 32, 48, 64)}, 128: big[128], 256: big[256]}
imgs[256].save(OUT / "agent-jo-jobs.ico", format="ICO",
               sizes=[(s, s) for s in order],
               append_images=[imgs[s] for s in order if s != 256])
# into place
icons = ROOT / "web_jobs" / "icons"
for s in (512, 384, 256, 192, 180):
    shutil.copyfile(OUT / f"icon-{s}.png", icons / f"icon-{s}.png")
shutil.copyfile(OUT / "small-32.png", icons / "icon-32.png")
shutil.copyfile(OUT / "small-16.png", icons / "icon-16.png")
shutil.copyfile(OUT / "maskable-512.png", icons / "maskable-512.png")
for s in (512, 192, 180):
    shutil.copyfile(OUT / f"icon-{s}.png", ROOT / "web_phone" / f"icon-{s}.png")
shutil.copyfile(OUT / "agent-jo-jobs.ico", ROOT / "agent-jo-jobs.ico")
shutil.copyfile(OUT / "logo-1024.png", ROOT / "branding" / "agent-jo-jobs-logo-1024.png")
print("ok", sorted(p.name for p in OUT.iterdir()))
