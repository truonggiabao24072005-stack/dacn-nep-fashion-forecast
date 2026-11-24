"""Product-level comparison from published database forecasts, with missing gaps."""

from html import escape

from store.forecast.replenishment import month_add
from store.models import ForecastValue, MonthlySales


def comparison_rows(unit, model, target):
    start = max(unit.dataset_version.coverage_start, month_add(target, -4))
    actual = dict(
        MonthlySales.objects.filter(
            forecast_unit=unit,
            month__gte=start,
            month__lte=target,
            observation_status__in=["OBSERVED", "VERIFIED_ZERO"],
        ).values_list("month", "target_qty")
    )
    forecast = {}
    for value in (
        ForecastValue.objects.filter(
            forecast_unit=unit,
            run__model_result=model,
            run__status="SUCCEEDED",
            run__target_month__gte=start,
            run__target_month__lte=target,
            result_status="VALID",
        )
        .select_related("run")
        .order_by("run__pk")
    ):
        forecast.setdefault(value.run.target_month, value.nonnegative_value)
    rows = []
    month = start
    while month <= target:
        a, p = actual.get(month), forecast.get(month)
        rows.append(
            {
                "month": month,
                "actual": a,
                "forecast": p,
                "difference": p - a if p is not None and a is not None else None,
            }
        )
        month = month_add(month, 1)
    return rows


def comparison_svg(rows):
    """Two aligned panels: quantities and signed differences in source units."""
    width, height = 960, 490
    left, right = 78, 890
    top, bottom = 60, 270
    values = [float(r[k]) for r in rows for k in ["actual", "forecast"] if r[k] is not None]
    maximum = max(values + [1]) * 1.15
    xs = [left + (right - left) * i / max(1, len(rows) - 1) for i in range(len(rows))]
    y = lambda v: bottom - float(v) / maximum * (bottom - top)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Dự đoán và thực tế; chênh lệch dương là dự đoán dư, âm là dự đoán thiếu.">',
        '<rect width="960" height="490" fill="white"/><g font-family="Arial,sans-serif" font-size="17" fill="#273c33">',
        '<text x="78" y="27">Số lượng sản phẩm</text>',
        '<path d="M570 22h28" stroke="#1b6c50" stroke-width="3"/><text x="609" y="28">Thực tế</text>',
        '<path d="M745 22h28" stroke="#bc7023" stroke-width="3" stroke-dasharray="7 4"/><text x="784" y="28">Dự đoán</text>',
    ]
    for i in range(5):
        v = maximum * i / 4
        yy = y(v)
        svg.append(
            f'<path d="M{left} {yy:.2f}H{right}" stroke="#e2e8e3"/><text x="66" y="{yy+6:.2f}" text-anchor="end">{v:.0f}</text>'
        )
    for key, color, dash in [
        ("actual", "#1b6c50", ""),
        ("forecast", "#bc7023", ' stroke-dasharray="7 4"'),
    ]:
        previous = None
        for i, row in enumerate(rows):
            value = row[key]
            if value is None:
                previous = None
                continue
            xx, yy = xs[i], y(value)
            if previous:
                svg.append(
                    f'<path d="M{previous[0]:.2f} {previous[1]:.2f}L{xx:.2f} {yy:.2f}" fill="none" stroke="{color}" stroke-width="3"{dash}/>'
                )
            svg.append(f'<circle cx="{xx:.2f}" cy="{yy:.2f}" r="5" fill="{color}"/>')
            previous = (xx, yy)
    svg.append(
        '<text x="78" y="310">Chênh lệch = Dự đoán − Thực tế</text><text x="78" y="330" font-size="15">Dương: dự đoán dư · Âm: dự đoán thiếu</text>'
    )
    zero = 400
    scale = max([abs(float(r["difference"])) for r in rows if r["difference"] is not None] + [1])
    svg.append(
        f'<path d="M{left} {zero}H{right}" stroke="#87998f"/><text x="66" y="406" text-anchor="end">0</text>'
    )
    for xx, row in zip(xs, rows):
        diff = row["difference"]
        if diff is not None:
            hh = float(diff) / scale * 37
            color = "#aa493d" if diff < 0 else "#457e67"
            svg.append(
                f'<rect x="{xx-17:.2f}" y="{min(zero,zero-hh):.2f}" width="34" height="{max(abs(hh),1):.2f}" fill="{color}"/><text x="{xx:.2f}" y="{zero-hh-8 if hh>=0 else zero-hh+18:.2f}" text-anchor="middle">{float(diff):+.2f}</text>'
            )
        else:
            svg.append(
                f'<text x="{xx:.2f}" y="385" text-anchor="middle" font-size="14">Chưa đủ dữ liệu</text>'
            )
        svg.append(
            f'<text x="{xx:.2f}" y="480" text-anchor="middle">{escape(row["month"].strftime("%m/%Y"))}</text>'
        )
    return "".join(svg) + "</g></svg>"
