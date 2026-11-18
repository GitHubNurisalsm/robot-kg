"""Геометрия SVG-графиков, считается на сервере.

Шаблон получает готовые координаты и подписи (автоэкранирование Django),
поэтому графики работают без JavaScript и внешних библиотек.
Спецификации: столбец <= 24px, скругление 4px только на конце данных,
зазор >= 2px, линия 2px, конечная точка r=4 с кольцом цвета фона,
сетка — тонкие сплошные линии.
"""

import math
from decimal import Decimal

WIDTH = 520   # близко к реальной ширине панели: подписи не мельчают при масштабе
HEIGHT = 230
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 18, 30
MAX_BAR = 24
RADIUS = 4


def nice_max(value: float) -> float:
    """Округлённый верх шкалы: 1, 2, 2.5, 5 × 10^n."""
    if value <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(value))
    for m in (1, 2, 2.5, 5, 10):
        if value <= m * exp:
            return m * exp
    return 10 * exp


def compact(value: float) -> str:
    v = float(value)
    for div, suf in ((1e9, " млрд"), (1e6, " млн"), (1e3, " тыс.")):
        if abs(v) >= div:
            n = v / div
            num = f"{n:.1f}".rstrip("0").rstrip(".").replace(".", ",")
            return num + suf
    return f"{v:,.0f}".replace(",", " ")


def full(value) -> str:
    return f"{float(value):,.0f}".replace(",", " ")


def _bar_path(x, y, w, h) -> str:
    """Столбец: скруглён сверху (конец данных), прямой у базовой линии."""
    if h <= 0:
        return ""
    r = min(RADIUS, w / 2, h)
    b = y + h
    return (f"M{x:.1f},{b:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{b:.1f}Z")


def _frame(max_value: float):
    # Круглый ШАГ (1/2/2,5/5 × 10ⁿ), а не круглый максимум: 0 / 1 / 2 / 3 / 4 млн.
    step = nice_max(max_value / 4) if max_value > 0 else 1
    if step < 1 and max_value >= 1:
        step = 1  # целочисленные шкалы для счётчиков
    top = step * 4
    plot_h = HEIGHT - PAD_T - PAD_B
    ticks = []
    for i in range(5):
        v = top * i / 4
        ticks.append({"y": round(PAD_T + plot_h - plot_h * i / 4, 1), "label": compact(v)})
    return top, plot_h, ticks


def _x_labels(dates, step_x, offset):
    n = len(dates)
    every = 1 if n <= 7 else (7 if n <= 31 else 21)
    labels = []
    for i, d in enumerate(dates):
        if i % every == 0 or i == n - 1:
            labels.append({"x": round(PAD_L + offset + i * step_x, 1), "label": d.strftime("%d.%m")})
    # последняя подпись не должна наезжать на предыдущую
    if len(labels) >= 2 and labels[-1]["x"] - labels[-2]["x"] < 34:
        labels.pop(-2)
    return labels


def column_chart(points: list[tuple], unit: str = "") -> dict:
    """points: [(date, value)] -> столбцы с хит-зонами на всю высоту дня."""
    values = [float(v) for _, v in points]
    top, plot_h, ticks = _frame(max(values, default=0))
    n = max(len(points), 1)
    slot = (WIDTH - PAD_L - PAD_R) / n
    bar_w = max(1.0, min(MAX_BAR, slot - 2))  # зазор >= 2px
    base = PAD_T + plot_h
    bars = []
    for i, (d, v) in enumerate(points):
        h = plot_h * float(v) / top if top else 0
        x = PAD_L + i * slot + (slot - bar_w) / 2
        bars.append({
            "path": _bar_path(x, base - h, bar_w, h),
            "hit_x": round(PAD_L + i * slot, 1), "hit_w": round(slot, 1),
            "cx": round(x + bar_w / 2, 1),
            "tip_value": f"{full(v)}{unit}", "tip_label": d.strftime("%d.%m.%Y"),
        })
    peak = max(range(len(values)), key=values.__getitem__) if values and max(values) > 0 else None
    label = None
    if peak is not None:
        b = bars[peak]
        label = {"x": b["cx"], "y": round(base - plot_h * values[peak] / top - 6, 1),
                 "text": compact(values[peak])}
    return {"w": WIDTH, "h": HEIGHT, "pad_l": PAD_L, "right": WIDTH - PAD_R, "base": base,
            "ticks": ticks, "bars": bars, "xlabels": _x_labels([d for d, _ in points], slot, slot / 2),
            "peak": label, "empty": not any(values)}


def line_chart(points: list[tuple], unit: str = "") -> dict:
    values = [float(v) for _, v in points]
    top, plot_h, ticks = _frame(max(values, default=0))
    n = len(points)
    step = (WIDTH - PAD_L - PAD_R) / max(n - 1, 1)
    base = PAD_T + plot_h
    coords = [(PAD_L + i * step, base - (plot_h * v / top if top else 0)) for i, v in enumerate(values)]
    line = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in coords) if coords else ""
    area = f"{line}L{coords[-1][0]:.1f},{base:.1f}L{coords[0][0]:.1f},{base:.1f}Z" if coords else ""
    hits = [{
        "x": round(x - step / 2, 1), "w": round(step, 1), "cx": round(x, 1), "cy": round(y, 1),
        "tip_value": f"{full(values[i])}{unit}", "tip_label": points[i][0].strftime("%d.%m.%Y"),
    } for i, (x, y) in enumerate(coords)]
    end = None
    if coords:
        end = {"x": round(coords[-1][0], 1), "y": round(coords[-1][1], 1), "text": compact(values[-1])}
    return {"w": WIDTH, "h": HEIGHT, "pad_l": PAD_L, "right": WIDTH - PAD_R, "base": base,
            "ticks": ticks, "line": line, "area": area, "hits": hits, "end": end,
            "xlabels": _x_labels([d for d, _ in points], step, 0), "empty": not any(values)}


def bar_rows(rows: list[dict], value_key: str, label_key: str, money: bool = False) -> list[dict]:
    """Горизонтальные полосы (HTML/CSS): ширина в % от максимума."""
    vmax = max((float(r[value_key] or 0) for r in rows), default=0)
    out = []
    for r in rows:
        v = float(r[value_key] or 0)
        out.append({**r, "label": r[label_key] or "—", "pct": round(100 * v / vmax, 1) if vmax else 0,
                    "display": full(v) + (" сом" if money else "")})
    return out


def pct(ratio) -> str:
    """0.1234 -> '12,3 %'; None -> '—' (нет базы для расчёта)."""
    if ratio is None:
        return "—"
    return f"{ratio * 100:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "\u00a0%"


def as_decimal_str(v) -> str:
    return full(v if v is not None else Decimal("0"))
