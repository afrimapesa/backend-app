from decimal import Decimal as D

import pytest

from apps.ingestion.base import RecordRejected
from apps.ingestion.validators import check_against_mid

MID = D("2000")


@pytest.mark.parametrize(
    "rate",
    [
        "2000",  # at mid
        "1960",  # 2% margin, typical
        "1800.01",  # just inside the 10% limit
        "2020",  # 1% promo above mid
        "2059.99",  # just inside the 3% limit above
    ],
)
def test_plausible_rates_pass(rate):
    check_against_mid(D(rate), MID)


@pytest.mark.parametrize(
    ("rate", "message"),
    [
        ("1799", "below mid-market"),
        ("200", "below mid-market"),  # decimal point slipped
        ("2061", "above mid-market"),
        ("20000", "above mid-market"),  # inverted / extra zero
        ("0", "Non-positive"),
        ("-5", "Non-positive"),
    ],
)
def test_implausible_rates_rejected(rate, message):
    with pytest.raises(RecordRejected, match=message):
        check_against_mid(D(rate), MID)


def test_missing_mid_rate_rejects():
    with pytest.raises(RecordRejected, match="No fresh mid-market rate"):
        check_against_mid(D("2000"), None)


def test_custom_thresholds():
    check_against_mid(D("1700"), MID, max_below=D("0.20"))
    with pytest.raises(RecordRejected):
        check_against_mid(D("2010"), MID, max_above=D("0"))
