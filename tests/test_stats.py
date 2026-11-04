import numpy as np
import pytest

from insights import stats as st


def test_binom_upper_matches_hand_calculation():
    assert st.binom_upper(2, 2, 0.5) == pytest.approx(0.25)
    assert st.binom_upper(1, 2, 0.5) == pytest.approx(0.75)


def test_binom_lower_zero_successes():
    assert st.binom_lower(0, 10, 0.3) == pytest.approx(0.7**10)


def test_run_probability_single_run_of_full_length():
    assert st.run_probability(5, 5, 0.5) == pytest.approx(0.5**5)


def test_run_probability_never_zero_for_positive_rate_and_capped_at_one():
    assert st.run_probability(3, 100, 0.01) > 0
    assert st.run_probability(1, 1000, 0.9) == 1.0


def test_fisher_upper_identical_groups_is_not_significant():
    assert st.fisher_upper(10, 20, 10, 20) > 0.5


def test_benjamini_hochberg_known_values():
    adjusted = st.benjamini_hochberg([0.01, 0.04, 0.03, 0.5])
    assert adjusted == pytest.approx([0.04, 0.0533333, 0.0533333, 0.5], rel=1e-3)


def test_benjamini_hochberg_all_noise_survives_nothing():
    rng = np.random.default_rng(1)
    assert (st.benjamini_hochberg(rng.uniform(size=5000)) < 0.1).sum() < 10
