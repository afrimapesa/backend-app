from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from apps.remittance.engine import (
    FeeSchedule,
    ProviderQuote,
    QuoteResult,
    calculate,
    rank_quotes,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def make_quote(
    provider: str = "wise",
    fx_rate: str = "1950.50",
    flat: str = "0",
    pct: str = "0",
    observed_at: datetime = NOW,
    update_interval: timedelta = HOUR,
    **kwargs,
) -> ProviderQuote:
    return ProviderQuote(
        provider=provider,
        fx_rate=D(fx_rate),
        fee=FeeSchedule(flat=D(flat), pct=D(pct)),
        observed_at=observed_at,
        update_interval=update_interval,
        **kwargs,
    )


def price(quote: ProviderQuote, amount: str = "100", fx_mid: str = "2000") -> QuoteResult:
    result = calculate(quote, D(amount), D(fx_mid), NOW)
    assert result is not None
    return result


class TestWorkedExample:
    """GBP 100 -> NGN with a £0.99 + 0.5% fee at 1950.50, mid-market 2000."""

    @pytest.fixture
    def result(self) -> QuoteResult:
        return price(make_quote(flat="0.99", pct="0.005"))

    def test_fee(self, result):
        assert result.transfer_fee == D("1.49")  # 0.99 + 100 * 0.005

    def test_net_payout(self, result):
        assert result.net_payout == D("192143.75")  # 98.51 * 1950.50 = 192143.755, rounded down

    def test_effective_rate(self, result):
        assert result.effective_rate == D("1921.437500")

    def test_fx_markup(self, result):
        assert result.fx_markup_pct == D("0.024750")  # (2000 - 1950.5) / 2000

    def test_total_cost_vs_mid_market(self, result):
        assert result.total_cost == D("3.93")  # 100 - 192143.75 / 2000
        assert result.total_cost_pct == D("0.039300")

    def test_carries_quote_metadata(self, result):
        assert result.provider == "wise"
        assert result.fx_mid == D("2000")
        assert result.observed_at == NOW
        assert result.rank is None


class TestFees:
    def test_zero_fee_pays_out_full_amount(self):
        result = price(make_quote(fx_rate="2000"))
        assert result.transfer_fee == 0
        assert result.net_payout == D("200000.00")
        assert result.total_cost == 0

    def test_flat_only(self):
        assert price(make_quote(flat="2.99")).transfer_fee == D("2.99")

    def test_percentage_only(self):
        assert price(make_quote(pct="0.01"), amount="250").transfer_fee == D("2.50")

    def test_fee_rounds_half_up_to_minor_units(self):
        # 33.33 * 0.015 = 0.49995 -> 0.50
        assert price(make_quote(pct="0.015"), amount="33.33").transfer_fee == D("0.50")

    def test_fee_respects_zero_decimal_currency(self):
        quote = make_quote(pct="0.015")
        result = calculate(quote, D("1001"), D("2000"), NOW, send_minor_units=0)
        assert result is not None
        assert result.transfer_fee == D("15")  # 15.015 -> 15

    def test_payout_rounds_down(self):
        # 1 * 1.239 = 1.239 -> 1.23, never overstate what the recipient receives
        assert price(make_quote(fx_rate="1.239"), amount="1", fx_mid="1.24").net_payout == D("1.23")

    def test_fee_equal_to_amount_is_ineligible(self):
        assert calculate(make_quote(flat="5"), D("5"), D("2000"), NOW) is None

    def test_fee_exceeding_amount_is_ineligible(self):
        assert calculate(make_quote(flat="10"), D("5"), D("2000"), NOW) is None

    def test_fee_just_below_amount_is_eligible(self):
        result = price(make_quote(flat="4.99", fx_rate="2000"), amount="5")
        assert result.net_payout == D("20.00")

    def test_provider_better_than_mid_market_gives_negative_cost(self):
        result = price(make_quote(fx_rate="2010"))
        assert result.fx_markup_pct < 0
        assert result.total_cost < 0

    @pytest.mark.parametrize(
        ("flat", "pct"), [("-1", "0"), ("0", "-0.01"), ("0", "1"), ("0", "1.5")]
    )
    def test_invalid_fee_schedule(self, flat, pct):
        with pytest.raises(ValueError):
            FeeSchedule(flat=D(flat), pct=D(pct))

    def test_float_inputs_rejected(self):
        with pytest.raises(TypeError):
            FeeSchedule(flat=0.99)  # type: ignore[arg-type]

    def test_string_inputs_accepted(self):
        assert FeeSchedule(flat="0.99", pct="0.005").fee_for(D("100")) == D("1.49")  # type: ignore[arg-type]


class TestLimits:
    def test_below_minimum_is_ineligible(self):
        assert calculate(make_quote(min_amount=D("50")), D("49.99"), D("2000"), NOW) is None

    def test_above_maximum_is_ineligible(self):
        assert calculate(make_quote(max_amount=D("5000")), D("5000.01"), D("2000"), NOW) is None

    def test_limits_are_inclusive(self):
        quote = make_quote(min_amount=D("50"), max_amount=D("5000"))
        assert calculate(quote, D("50"), D("2000"), NOW) is not None
        assert calculate(quote, D("5000"), D("2000"), NOW) is not None

    def test_min_above_max_rejected(self):
        with pytest.raises(ValueError):
            make_quote(min_amount=D("100"), max_amount=D("50"))


class TestValidation:
    @pytest.mark.parametrize("amount", ["0", "-10"])
    def test_non_positive_amount(self, amount):
        with pytest.raises(ValueError):
            calculate(make_quote(), D(amount), D("2000"), NOW)

    @pytest.mark.parametrize("fx_mid", ["0", "-1"])
    def test_non_positive_mid_rate(self, fx_mid):
        with pytest.raises(ValueError):
            calculate(make_quote(), D("100"), D(fx_mid), NOW)

    @pytest.mark.parametrize("fx_rate", ["0", "-1"])
    def test_non_positive_provider_rate(self, fx_rate):
        with pytest.raises(ValueError):
            make_quote(fx_rate=fx_rate)

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValueError):
            make_quote(observed_at=datetime(2026, 10, 16, 12, 0))  # noqa: DTZ001


class TestStaleness:
    """Exit criterion E05: quotes older than 2x the update interval are flagged."""

    def test_fresh(self):
        assert not price(make_quote(observed_at=NOW - HOUR)).is_stale

    def test_exactly_twice_interval_is_not_stale(self):
        assert not price(make_quote(observed_at=NOW - 2 * HOUR)).is_stale

    def test_older_than_twice_interval_is_stale(self):
        quote = make_quote(observed_at=NOW - 2 * HOUR - timedelta(seconds=1))
        assert price(quote).is_stale

    def test_uses_provider_interval(self):
        quote = make_quote(
            observed_at=NOW - timedelta(minutes=11), update_interval=timedelta(minutes=5)
        )
        assert price(quote).is_stale


class TestRanking:
    def test_ranks_by_net_payout_descending(self):
        quotes = [
            make_quote("low", fx_rate="1900"),
            make_quote("high", fx_rate="1990"),
            make_quote("mid", fx_rate="1950"),
        ]
        ranked = rank_quotes(quotes, D("100"), D("2000"), NOW)
        assert [r.provider for r in ranked] == ["high", "mid", "low"]
        assert [r.rank for r in ranked] == [1, 2, 3]

    def test_zero_fee_with_bad_rate_loses_to_fee_with_good_rate(self):
        """The core insight: 'no fee' providers often hide the cost in the FX rate."""
        quotes = [
            make_quote("no-fee", fx_rate="1900"),
            make_quote("has-fee", fx_rate="1990", flat="2.99"),
        ]
        ranked = rank_quotes(quotes, D("100"), D("2000"), NOW)
        assert ranked[0].provider == "has-fee"  # 97.01 * 1990 = 193049.90 > 190000

    def test_returns_top_five(self):
        quotes = [make_quote(f"p{i}", fx_rate=str(1900 + i)) for i in range(8)]
        ranked = rank_quotes(quotes, D("100"), D("2000"), NOW)
        assert len(ranked) == 5
        assert [r.provider for r in ranked] == ["p7", "p6", "p5", "p4", "p3"]

    def test_limit_none_returns_all(self):
        quotes = [make_quote(f"p{i}", fx_rate=str(1900 + i)) for i in range(8)]
        assert len(rank_quotes(quotes, D("100"), D("2000"), NOW, limit=None)) == 8

    def test_ineligible_quotes_excluded_before_ranking(self):
        quotes = [
            make_quote("too-small", fx_rate="1999", min_amount=D("500")),
            make_quote("ok", fx_rate="1900"),
        ]
        ranked = rank_quotes(quotes, D("100"), D("2000"), NOW)
        assert [r.provider for r in ranked] == ["ok"]
        assert ranked[0].rank == 1

    def test_tie_broken_by_lower_fee(self):
        # Both pay out exactly 198,000; the zero-fee quote wins the tie.
        quotes = [
            make_quote("fee", fx_rate="2000", flat="1"),  # 99 * 2000 = 198000
            make_quote("no-fee", fx_rate="1980"),  # 100 * 1980 = 198000
        ]
        ranked = rank_quotes(quotes, D("100"), D("2000"), NOW)
        assert [r.provider for r in ranked] == ["no-fee", "fee"]

    def test_tie_broken_by_speed_then_name(self):
        quotes = [
            make_quote("slow", transfer_time=timedelta(days=2)),
            make_quote("unknown"),
            make_quote("fast", transfer_time=timedelta(minutes=10)),
            make_quote("also-fast", transfer_time=timedelta(minutes=10)),
        ]
        ranked = rank_quotes(quotes, D("100"), D("2000"), NOW)
        assert [r.provider for r in ranked] == ["also-fast", "fast", "slow", "unknown"]

    def test_empty(self):
        assert rank_quotes([], D("100"), D("2000"), NOW) == []
