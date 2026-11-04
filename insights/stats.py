"""Probability helpers. Each returns the chance of seeing a result this extreme by luck."""
import numpy as np
from scipy import stats


def binom_upper(k, n, p):
    """P(X >= k), X ~ Binomial(n, p)."""
    return stats.binom.sf(np.asarray(k) - 1, n, p)


def binom_lower(k, n, p):
    """P(X <= k), X ~ Binomial(n, p)."""
    return stats.binom.cdf(k, n, p)


def binom_two_sided(k, n, p):
    return np.minimum(1.0, 2 * np.minimum(binom_upper(k, n, p), binom_lower(k, n, p)))


def poisson_upper(k, mu):
    """P(X >= k), X ~ Poisson(mu)."""
    return stats.poisson.sf(np.asarray(k) - 1, mu)


def fisher_upper(k1, n1, k2, n2):
    """One-sided Fisher exact test that group 1 has a higher rate than group 2."""
    return stats.hypergeom.sf(np.asarray(k1) - 1, np.asarray(n1) + n2, np.asarray(k1) + k2, n1)


def run_probability(length, n, p):
    """Upper bound on P(a run of `length` successes occurs somewhere in n independent trials)."""
    length, n, p = map(np.asarray, (length, n, p))
    return np.minimum(1.0, p**length + np.maximum(n - length, 0) * (1 - p) * p**length)


def benjamini_hochberg(p_values):
    """Adjusted p-values controlling the false discovery rate across all tests."""
    p = np.asarray(p_values, dtype=float)
    if p.size == 0:
        return p
    order = np.argsort(p)
    adjusted = p[order] * p.size / np.arange(1, p.size + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.minimum(adjusted, 1.0)
    return result
