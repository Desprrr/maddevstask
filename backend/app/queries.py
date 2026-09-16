import datetime as dt

from sqlalchemy import Select, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.incidents import monitoring_gap_threshold
from app.models.check import Check
from app.models.check_result import CheckResult


def checks_with_latest_result(*where) -> Select:
    """Проверки вместе с их последним результатом (или None).

    LATERAL + `ORDER BY checked_at DESC LIMIT 1` на каждую проверку — это обратный
    проход по индексу (check_id, checked_at) с остановкой на первой строке, то есть
    стоимость зависит от числа проверок, а не от объёма истории. `DISTINCT ON
    (check_id)` в индекс не попадал и сортировал всю check_results."""
    latest = (
        select(CheckResult)
        .where(CheckResult.check_id == Check.id)
        .order_by(CheckResult.checked_at.desc())
        .limit(1)
        .lateral("latest_result")
    )
    latest_result = aliased(CheckResult, latest)
    return select(Check, latest_result).outerjoin(latest_result, true()).where(*where).order_by(Check.id)


async def monitoring_gaps(
    db: AsyncSession, check: Check, since: dt.datetime, until: dt.datetime
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Интервалы периода [since, until], за которые у проверки нет результатов дольше
    порога разрыва (2×интервал + таймаут): сервер мониторинга не работал или проверка
    стояла на паузе. Это не падение сайта — в доступность не входит, на графике
    показывается отдельно.

    Считается по сырым результатам через `lag()`, а не по бакетам: при часовых/дневных
    бакетах получасовой простой иначе растворился бы внутри бакета."""
    threshold = monitoring_gap_threshold(check)
    in_range = (CheckResult.check_id == check.id, CheckResult.checked_at >= since)

    ordered = select(
        CheckResult.checked_at.label("at"),
        func.lag(CheckResult.checked_at).over(order_by=CheckResult.checked_at).label("prev"),
    ).where(*in_range).subquery()
    interior = (
        await db.execute(
            select(ordered.c.prev, ordered.c.at)
            .where(ordered.c.at - ordered.c.prev > threshold)
            .order_by(ordered.c.at)
        )
    ).all()
    first, last = (
        await db.execute(select(func.min(CheckResult.checked_at), func.max(CheckResult.checked_at)).where(*in_range))
    ).one()

    # до создания проверки данных и не должно было быть — это не разрыв
    observed_from = max(since, check.created_at)
    gaps: list[tuple[dt.datetime, dt.datetime]] = []
    if first is None:
        if until - observed_from > threshold:
            gaps.append((observed_from, until))
        return gaps
    if first - observed_from > threshold:
        gaps.append((observed_from, first))
    gaps.extend((prev, at) for prev, at in interior)
    if until - last > threshold:
        gaps.append((last, until))
    return gaps
