from sqlalchemy import Select, select, true
from sqlalchemy.orm import aliased

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
