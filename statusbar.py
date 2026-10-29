import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

HOME = Path.home() / ".claude"
DIR = HOME / "statusbar"
SETTINGS = HOME / "settings.json"
SEGMENTS = ["model", "project", "context", "cache", "5h", "7d", "cost"]
SAMPLE = {
    "model": {"display_name": "Opus 5.5"},
    "workspace": {"current_dir": "/home/me/my-project"},
    "context_window": {"current_usage": {"input_tokens": 1200, "cache_creation_input_tokens": 8000, "cache_read_input_tokens": 33000}},
    "prompt_cache": {"caching_observed": True, "expires_at": time.time() + 754},
    "rate_limits": {"five_hour": {"used_percentage": 22}, "seven_day": {"used_percentage": 84}},
    "cost": {"total_cost_usd": 1.37},
}


def paint(code, text):
    return f"\033[{code}m{text}\033[0m"


def level(pct):
    return 32 if pct < 50 else 33 if pct < 80 else 31


def collect(p):
    out = []
    model = (p.get("model") or {}).get("display_name")
    if model:
        out.append(("model", "", model, None))
    cwd = (p.get("workspace") or {}).get("current_dir") or p.get("cwd") or ""
    project = cwd.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if project:
        out.append(("project", "", project, None))
    usage = (p.get("context_window") or {}).get("current_usage")
    if isinstance(usage, dict):
        tokens = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        out.append(("context", "ctx", f"{tokens / 1000:.0f}k" if tokens >= 1000 else str(tokens), None))
    cache = p.get("prompt_cache") or {}
    if cache.get("caching_observed"):
        left = (cache.get("expires_at") or 0) - time.time()
        out.append(("cache", "cache", f"{int(left // 60)}m" if left > 0 else "cold", None))
    limits = p.get("rate_limits") or {}
    for key, window in (("5h", "five_hour"), ("7d", "seven_day")):
        pct = (limits.get(window) or {}).get("used_percentage")
        if isinstance(pct, (int, float)):
            out.append((key, key, f"{pct:.0f}%", pct))
    cost = (p.get("cost") or {}).get("total_cost_usd")
    if isinstance(cost, (int, float)):
        out.append(("cost", "", f"${cost:.2f}", None))
    return out


def plain(segs):
    return " | ".join(f"{label} {text}".strip() for label, text, pct in segs)


def color(segs):
    parts = []
    for label, text, pct in segs:
        value = paint(36 if pct is None else level(pct), text)
        parts.append(f"{paint(90, label)} {value}" if label else value)
    return paint(90, " │ ").join(parts)


def bars(segs):
    parts = []
    for label, text, pct in segs:
        if pct is None:
            parts.append(f"{paint(90, label)} {paint(36, text)}" if label else paint(36, text))
        else:
            full = round(min(pct, 100) / 20)
            parts.append(f"{paint(90, label)} {paint(level(pct), '▰' * full + '▱' * (5 - full))} {text}")
    return "  ".join(parts)


def blocks(segs):
    out = ""
    for i, (label, text, pct) in enumerate(segs):
        code = f"30;{level(pct) + 10}" if pct is not None else ("97;45", "97;44")[i] if i < 2 else "97;100"
        out += paint(code, f" {label} {text} " if label else f" {text} ")
    return out


def minimal(segs):
    return "  ".join(text if pct is None else paint(level(pct), text) for label, text, pct in segs)


DESIGNS = {"plain": plain, "color": color, "bars": bars, "blocks": blocks, "minimal": minimal}


def render(payload, cfg):
    segs = [s[1:] for s in collect(payload) if s[0] in cfg["segments"]]
    return DESIGNS[cfg["design"]](segs)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def ask(prompt, count):
    while True:
        answer = input(f"{prompt} [1]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer)
        print(f"  Enter a number from 1 to {count}.")


def key():
    if os.name == "nt":
        import msvcrt
        c = msvcrt.getwch()
        if c in ("\x00", "\xe0"):
            return {"H": "up", "P": "down"}.get(msvcrt.getwch())
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            c = sys.stdin.read(1)
            if c == "\x1b":
                return {"[A": "up", "[B": "down"}.get(sys.stdin.read(2))
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if c == "\x03":
        raise KeyboardInterrupt
    return c


def pick_segments():
    if not sys.stdin.isatty():
        return SEGMENTS
    items = SEGMENTS + ["Continue"]
    chosen, pos = set(SEGMENTS), 0
    print("\nSegments  (↑/↓ move, Enter toggle)")
    while True:
        for i, item in enumerate(items):
            pointer = paint(36, "❯") if i == pos else " "
            mark = "   " if item == "Continue" else f"[{paint(32, '✔')}]" if item in chosen else "[ ]"
            print(f"\033[2K  {pointer} {mark} {item}")
        k = key()
        if k == "up":
            pos = (pos - 1) % len(items)
        elif k == "down":
            pos = (pos + 1) % len(items)
        elif k in ("\r", "\n", " "):
            if items[pos] == "Continue":
                return [s for s in SEGMENTS if s in chosen]
            chosen ^= {items[pos]}
        print(f"\033[{len(items)}A", end="")


def install(previous):
    names = list(DESIGNS)
    full = {"segments": SEGMENTS}
    print("\nDesigns:")
    for i, name in enumerate(names, 1):
        print(f"  {i}) {name:<8} {render(SAMPLE, {**full, 'design': name})}")
    design = names[ask("Design", len(names)) - 1]
    segments = pick_segments()
    cfg = {"design": design, "segments": segments, "previous": previous}
    print(f"\nPreview: {render(SAMPLE, cfg)}\n")

    DIR.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != (DIR / "statusbar.py").resolve():
        shutil.copy(__file__, DIR / "statusbar.py")
    save(DIR / "config.json", cfg)
    settings = load(SETTINGS)
    script = (DIR / "statusbar.py").as_posix()
    settings["statusLine"] = {"type": "command", "command": f'"{Path(sys.executable).as_posix()}" "{script}" --render', "padding": 0}
    save(SETTINGS, settings)
    print("Installed. Restart Claude Code to see it.")


def remove(cfg):
    settings = load(SETTINGS)
    if cfg.get("previous"):
        settings["statusLine"] = cfg["previous"]
    else:
        settings.pop("statusLine", None)
    save(SETTINGS, settings)
    shutil.rmtree(DIR, ignore_errors=True)
    print("Removed. Previous status line restored.")


def setup():
    os.system("")
    cfg = load(DIR / "config.json")
    if not cfg:
        HOME.mkdir(parents=True, exist_ok=True)
        return install(load(SETTINGS).get("statusLine"))
    print("Status bar is already installed.\n  1) Reinstall\n  2) Remove\n  3) Exit")
    choice = ask("Choose", 3)
    if choice == 1:
        install(cfg.get("previous"))
    elif choice == 2:
        remove(cfg)


COLORS = {30: "#1e1e1e", 31: "#f14c4c", 32: "#23d18b", 33: "#f5f543", 36: "#29b8db", 44: "#2472c8", 45: "#bc3fbc", 90: "#808080", 97: "#ffffff", 100: "#4d4d4d"}


def draw(line, y):
    x, w = 16, 8.4
    rects, spans = [], []
    fg, bg = "#d4d4d4", None
    for i, chunk in enumerate(re.split(r"\033\[([\d;]*)m", line)):
        if i % 2:
            fg, bg = "#d4d4d4", None
            for code in map(int, filter(None, chunk.split(";"))):
                if 40 <= code <= 47 or code == 100:
                    bg = COLORS.get(code, COLORS.get(code - 10))
                elif code:
                    fg = COLORS[code]
        elif chunk:
            if bg:
                rects.append(f'<rect x="{x:.1f}" y="{y - 15}" width="{len(chunk) * w:.1f}" height="20" fill="{bg}"/>')
            spans.append(f'<tspan x="{x:.1f}" textLength="{len(chunk) * w:.1f}" lengthAdjust="spacingAndGlyphs" fill="{fg}">{escape(chunk)}</tspan>')
            x += len(chunk) * w
    return "".join(rects) + f'<text y="{y}" xml:space="preserve">{"".join(spans)}</text>', x


def svg(lines, width=0):
    parts, ends = zip(*(draw(line, 25 + 20 * i) for i, line in enumerate(lines)))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{max(width, *ends) + 16:.0f}" height="{20 * len(lines) + 20}"'
        f' font-family="Consolas, Menlo, monospace" font-size="14">'
        f'<rect width="100%" height="100%" rx="6" fill="#1e1e1e"/>{"".join(parts)}</svg>'
    )


def make_svgs():
    docs = Path(__file__).parent / "docs"
    docs.mkdir(exist_ok=True)
    full = {"segments": SEGMENTS}
    for name in DESIGNS:
        (docs / f"{name}.svg").write_text(svg([render(SAMPLE, {**full, "design": name})]), encoding="utf-8")
    rule = paint(90, "─" * 76)
    hint = paint(90, "  ⏵⏵ auto mode on (shift+tab to cycle)")
    bar = "  " + render(SAMPLE, {**full, "design": "color"})
    session = [
        paint(90, "❯ ") + "add a health check endpoint",
        "",
        "● Added GET /health to server.py. It returns {\"status\": \"ok\"}.",
        "",
        rule,
        "❯ ",
        rule,
    ]
    (docs / "before.svg").write_text(svg(session + [hint]), encoding="utf-8")
    (docs / "after.svg").write_text(svg(session + [bar, hint]), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--render" in sys.argv:
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            print(render(json.loads(sys.stdin.read()), load(Path(__file__).parent / "config.json")))
        except Exception:
            print("")
    elif "--svg" in sys.argv:
        make_svgs()
    else:
        setup()


if __name__ == "__main__":
    main()
