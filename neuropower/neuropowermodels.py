#!/usr/bin/env python

"""
Fit a mixture model to a list of peak height T-values.
The model is introduced in the HBM poster:
http://www2.warwick.ac.uk/fac/sci/statistics/staff/academic-research/nichols/presentations/ohbm2015/Durnez-PeakPower-OHBM2015.pdf
"""
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
import nibabel as nib
from scipy import integrate
from scipy.stats import norm, beta
from scipy.stats import t as tdist
from scipy.optimize import minimize

from neuropower import cluster, peakdistribution, BUM


def altPDF(peaks, mu, sigma=None, exc=None, method='RFT'):
    """
    Returns probability density using a truncated normal distribution that we
    define as the distribution of local maxima in a GRF under the alternative
    hypothesis of activation.

    Parameters
    ----------
    peaks : :obj:`numpy.ndarray`
        List of peak heights (z-values).
    mu : :obj:`float`
        Mean from fitted normal distribution.
    sigma : :obj:`float`
        Standard deviation from fitted normal distribution.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    fa : :obj:`numpy.ndarray`
        Probability density of the peaks heights under Ha.
    """
    # Returns probability density of the alternative peak distribution
    peaks = np.asarray(peaks)
    if method == 'RFT':
        ksi = (peaks - mu) / sigma
        alpha = (exc - mu) / sigma
        num = 1. / sigma * norm.pdf(ksi)
        den = 1. - norm.cdf(alpha)
        fa = num / den
    elif method == 'CS':
        fa = np.array([peakdistribution.peakdens3D(y - mu, 1) for y in peaks])
    else:
        raise ValueError('Argument `method` must be either "RFT" or "CS"')
    return fa


def nulPDF(peaks, exc=None, method='RFT'):
    """
    Returns probability density of the null peak distribution.

    Parameters
    ----------
    peaks : :obj:`numpy.ndarray`
        List of peak heights (z-values).
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    f0 : :obj:`numpy.ndarray`
        Probability density of the peaks heights under H0.
    """
    peaks = np.asarray(peaks)
    if method == 'RFT':
        f0 = exc * np.exp(-exc * (peaks - exc))
    elif method == 'CS':
        f0 = np.array([peakdistribution.peakdens3D(x, 1) for x in peaks])
    else:
        raise ValueError('Argument `method` must be either "RFT" or "CS"')
    return f0


def altCDF(peaks, mu, sigma=None, exc=None, method="RFT"):
    """
    Returns the CDF of the alternative peak distribution

    Parameters
    ----------
    peaks : :obj:`numpy.ndarray`
        List of peak heights (z-values).
    mu : :obj:`float`
        Mean from fitted normal distribution.
    sigma : :obj:`float`
        Standard deviation from fitted normal distribution.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    Fa : :obj:`numpy.ndarray`
        Cumulative density of the peak heights under Ha.
    """
    peaks = np.asarray(peaks)
    if method == 'RFT':
        ksi = (peaks - mu) / sigma
        alpha = (exc - mu) / sigma
        Fa = (norm.cdf(ksi) - norm.cdf(alpha)) / (1 - norm.cdf(alpha))
    elif method == 'CS':
        Fa = np.array([integrate.quad(lambda x:peakdistribution.peakdens3D(x, 1), -20, y)[0] for y in peaks-mu])
    else:
        raise ValueError('Argument `method` must be either "RFT" or "CS"')
    return Fa


def TruncTau(mu, sigma, exc):
    """
    Calculates truncated tau value?

    Parameters
    ----------
    mu : :obj:`float`
        Mean from fitted normal distribution.
    sigma : :obj:`float`
        Standard deviation from fitted normal distribution.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)

    Returns
    -------
    tau : :obj:`float`
        Truncated tau value.
    """
    num = norm.cdf((exc - mu) / sigma)
    den = 1 - norm.pdf((exc - mu) / sigma)
    tau = num / den
    return tau


def _nulCDF(peaks, exc=None, method='RFT'):
    """
    Returns the CDF of the null peak distribution.

    Parameters
    ----------
    peaks : :obj:`numpy.ndarray`
        List of peak heights (z-values).
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    F0 : :obj:`numpy.ndarray`
        Cumulative density of the peak heights under H0.
    """
    peaks = np.asarray(peaks)
    if method == "RFT":
        F0 = 1 - np.exp(-exc * (peaks - exc))
    elif method == "CS":
        F0 = np.array([integrate.quad(lambda x:peakdistribution.peakdens3D(x, 1), -20, y)[0] for y in peaks])
    else:
        raise ValueError('Argument `method` must be either "RFT" or "CS"')
    return F0


def mixPDF(peaks, pi1, mu, sigma=None, exc=None, method='RFT'):
    """
    Returns the PDF of the mixture of null and alternative distributions.

    Parameters
    ----------
    peaks : :obj:`numpy.ndarray`
        A list of p-values associated with local maxima in the input image.
    pi1 : :obj:`float`
        Mixing weight.
    mu : :obj:`float`
        Mean from fitted normal distribution.
    sigma : :obj:`float`, optional
        Standard deviation from fitted normal distribution.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    f : :obj:`numpy.ndarray`
        Probability density of the mixture of null and alternative distributions.
    """
    peaks = np.array(peaks)
    if method == 'RFT':
        f0 = nulPDF(peaks, exc=exc, method='RFT')
        fa = altPDF(peaks, mu, sigma=sigma, exc=exc, method='RFT')
    elif method == 'CS':
        f0 = nulPDF(peaks, method='CS')
        fa = altPDF(peaks, mu, method='CS')
    else:
        raise ValueError('Argument `method` must be either "RFT" or "CS"')
    f = [(1 - pi1) * x + pi1 * y for x, y in zip(f0, fa)]
    return f


def _mixPDF_SLL(pars, peaks, pi1, exc=None, method='RFT'):
    """
    Returns the negative sum of the loglikelihood of the PDF with RFT.

    Parameters
    ----------
    pars : :obj:`list` of :obj:`float`
        One- or two-unit list of parameters. First parameter is ``mu``. Optional
        second parameter is ``sigma``.
    sigma : :obj:`float` or :obj:`None`
        Standard deviation from fitted normal distribution.
    peaks : :obj:`numpy.ndarray`
        A list of p-values associated with local maxima in the input image.
    pi1 : :obj:`float`
        Mixing weight.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    LL : :obj:`float`
        Negative sum of loglikelihood.
    """
    mu = pars[0]
    if method == 'RFT':
        sigma = pars[1]
        f = mixPDF(peaks, pi1=pi1, mu=mu, sigma=sigma, exc=exc, method='RFT')
    elif method == 'CS':
        f = mixPDF(peaks, pi1=pi1, mu=mu, method='CS')
    else:
        raise ValueError('Argument `method` must be either "RFT" or "CS"')
    LL = -sum(np.log(f))
    return LL


def modelfit(peaks, pi1, exc=None, n_iters=1, seed=None, method='RFT'):
    """
    Searches the maximum likelihood estimator for the mixture distribution of
    null and alternative.

    Parameters
    ----------
    peaks : :obj:`numpy.ndarray`
        1D array of z-values from peaks in statistical map.
    pi1 : :obj:`float`
        Mixing weight.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    n_iters : :obj:`int`, optional
        Number of iterations.
    seed : :obj:`int`, optional
        Random seed.
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.

    Returns
    -------
    out : :obj:`dict`
        Parameters for fitted normal distribution.
    """
    peaks = np.asarray(peaks)
    if seed is None:
        seed = np.random.uniform(0, 1000, 1)
    mus = np.random.uniform(exc+(1./exc),10,(n_iters,)) if method == 'RFT' else np.random.uniform(0,10,(n_iters,))
    sigmas = np.random.uniform(0.1, 10, (n_iters,)) if method=='RFT' else np.repeat(None, n_iters)
    best = []
    par = []
    for i in range(n_iters):
        if method == 'RFT':
            opt = minimize(_mixPDF_SLL, [mus[i], sigmas[i]], method='L-BFGS-B',
                           args=(peaks, pi1, exc, method),
                           bounds=((exc + (1. / exc), 50), (0.1, 50)))
        elif method == 'CS':
            opt = minimize(_mixPDF_SLL, [mus[i]], method='L-BFGS-B',
                           args=(peaks, pi1, exc, method), bounds=((0, 50),))
        else:
            raise ValueError('Argument `method` must be either "RFT" or "CS"')
        best.append(opt.fun)
        par.append(opt.x)
    minind = best.index(np.nanmin(best))
    out = {'maxloglikelihood': best[minind],
           'mu': par[minind][0],
           'sigma': par[minind][1] if method == 'RFT' else 'nan'}
    return out


def threshold(pvalues, fwhm, voxsize, n_voxels, alpha=0.05, exc=None):
    """Threshold p-values from peaks.

    exc : :obj:`float`
        Cluster defining threshold in Z.
    """
    # only RFT
    peakrange = np.arange(exc, 15, 0.001)
    pN = 1-_nulCDF(np.array(peakrange), exc=exc)
    # smoothness
    FWHM_vox = np.asarray(fwhm)/np.asarray(voxsize)
    resels = n_voxels/np.product(FWHM_vox)
    pN_RFT = resels*np.exp(-peakrange**2/2)*peakrange**2
    cutoff_UN = np.min(peakrange[pN<alpha])
    cutoff_BF = np.min(peakrange[pN<alpha/len(pvalues)])
    cutoff_RFT = np.min(peakrange[pN_RFT<alpha])
    #Benjamini-Hochberg
    pvals_sortind = np.argsort(pvalues)
    pvals_order = pvals_sortind.argsort()
    FDRqval = pvals_order/float(len(pvalues))*0.05
    reject = pvalues < FDRqval
    if reject.any():
        FDRc = np.max(pvalues[reject])
    else:
        FDRc = 0
    cutoff_BH = 'nan' if FDRc == 0 else min(peakrange[pN < FDRc])
    out = {'UN': cutoff_UN,
           'BF': cutoff_BF,
           'RFT': cutoff_RFT,
           'BH': cutoff_BH}
    return out


def BH(pvals, alpha):
    """
    Benjamini-Hochberg FDR-correct p-values.

    Parameters
    ----------
    pvals : :obj:`numpy.ndarray`
        Array of p-values.
    alpha : :obj:`float`
        Alpha value to correct p-values for.

    Returns
    -------
    FDRc : :obj:`numpy.ndarray`
        FDR-correct p-values.
    """
    pvals_sortind = np.argsort(pvals)
    pvals_order = pvals_sortind.argsort()
    FDRqval = pvals_order / float(len(pvals)) * alpha
    reject = pvals < FDRqval
    if np.sum(reject) == 0:
        FDRc = 0
    else:
        FDRc = np.max(pvals[reject])
    return FDRc


def run_power_analysis(input_img, n, fwhm=[8, 8, 8], mask_img=None, dtype='t',
                       design='one-sample', exc=0.001, alpha=0.05, method='RFT',
                       n_iters=1000, seed=None):
    """
    Parameters
    ----------
    input_img : :obj:`nibabel.Nifti1Image`
        Input image.
    n : :obj:`int`
        Total sample size from analysis.
    fwhm : :obj:`list`
        A list of FWHM values in mm of length 3.
    mask_img : :obj:`nibabel.Nifti1Image`, optional
        Mask image.
    dtype : {'t', 'z'}, optional
        Data type of input image.
    design : {'one-sample', 'two-sample'}, optional
        Design of analysis from input image.
    exc : :obj:`float`, optional
        Z-threshold (excursion threshold)
    alpha : :obj:`float`, optional
        Desired alpha.
    method : {'RFT', 'CS'}, optional
        Multiple comparisons correction method.
    n_iters : :obj:`int`, optional
        Number of iterations.
    seed : :obj:`int`, optional
        Random seed.

    Returns
    -------
    params : :obj:`dict`
        Parameters of fitted distributions.
    peak_df : :obj:`pandas.DataFrame`
        DataFrame of local maxima from statistical map, along with associated
        z-values and p-values.
    power_df : :obj:`pandas.DataFrame`
        DataFrame of power estimates using different multiple comparisons
        correction methods for different sample sizes.
    """
    spm = input_img.get_data()
    affine = input_img.affine
    voxel_size = input_img.header.get_zooms()
    if mask_img is not None:
        mask = mask_img.get_data()
    else:
        mask = (spm != 0).astype(int)
    n_voxels = np.sum(mask)

    if design == 'one-sample':
        df = n - 1
    elif design == 'two-sample':
        df = n - 2
    else:
        raise Exception('Unrecognized design: {0}'.format(design))

    z_u = norm.ppf(1 - exc)  # threshold in z
    if dtype == 'z':
        spm_z = spm.copy()
    elif dtype == 't':
        spm_z = -norm.ppf(tdist.cdf(-spm, df=df))
    else:
        raise Exception('Unrecognized data type: {0}'.format(dtype))

    peak_df = cluster.PeakTable(spm_z, z_u, mask)
    ijk = peak_df[['i', 'j', 'k']].values
    xyz = pd.DataFrame(data=nib.affines.apply_affine(affine, ijk), columns=['x', 'y', 'z'])
    peak_df = pd.concat([xyz, peak_df], axis=1)
    peak_df = peak_df.drop(['i', 'j', 'k'], axis=1)
    peak_df.index.name = 'peak index'
    z_values = peak_df['zval'].values
    p_values = peak_df['pval'].values

    # Fit models
    out1 = BUM.EstimatePi1(p_values, n_iters=n_iters)
    out2 = modelfit(z_values, pi1=out1['pi1'], exc=z_u, n_iters=n_iters,
                    seed=seed, method=method)
    params = {}
    params['z_u'] = z_u
    params['a'] = out1['a']
    params['pi1'] = out1['pi1']
    params['lambda'] = out1['lambda']
    params['mu'] = out2['mu']
    params['sigma'] = out2['sigma']
    params['mu_s'] = params['mu'] / np.sqrt(n)

    # Predict power for range of sample sizes
    thresholds = threshold(p_values, fwhm, voxel_size, n_voxels, alpha, z_u)
    powerpred_all = []
    test_ns = range(n, n+600)
    for s in test_ns:
        projected_effect = params['mu_s'] * np.sqrt(s)

        powerpred_s = {}
        for k, v in thresholds.items():
            if not v == 'nan':
                powerpred_s[k] = 1 - altCDF([v], projected_effect, params['sigma'],
                                            params['z_u'], method)[0]
        powerpred_s['sample size'] = s
        powerpred_all.append(powerpred_s)
    power_df = pd.DataFrame(powerpred_all)
    power_df = power_df.set_index('sample size', drop=True)
    power_df = power_df.loc[(power_df[power_df.columns]<1).all(axis=1)]
    return params, peak_df, power_df


def generate_figure(peak_df, params, method='RFT'):
    """
    Generate a matplotlib figure and axis object for Neuropower plots.

    Parameters
    ----------
    peak_df : :obj:`pandas.DataFrame`
        DataFrame of local maxima from statistical map, along with associated
        z-values and p-values.
    params : :obj:`dict`
        Parameters from fitted models.
    method : {'RFT', 'CS'}
        Multiple comparisons correction method.

    Returns
    -------
    fig : :obj:`matplotlib.figure.Figure`
        Shared figure object for p-value and z-value plots.
    axes : :obj:`numpy.ndarray` of :obj:`matplotlib.axes._subplots.AxesSubplot`
        Two axis objects for p-value and z-value plots.
    """
    p_values = peak_df['pval'].values
    z_values = peak_df['zval'].values
    z_u = params['z_u']
    a = params['a']
    pi1 = params['pi1']
    mu = params['mu']
    sigma = params['sigma']
    mu_s = params['mu_s']
    fig, axes = plt.subplots(ncols=2, figsize=(16, 7))

    # p-values
    x_min, x_max = np.floor(np.min(p_values)), np.ceil(np.max(p_values))
    x = np.linspace(x_min, x_max, 100)
    y_a = (pi1 * beta.pdf(x, a=a, b=1)) + 1 - pi1

    axes[0].hist(p_values, bins=np.arange(0,1.1,0.1), alpha=0.6,
                 label='observed distribution')
    axes[0].axhline(1-pi1, color='g', lw=5, alpha=0.6, label='null distribution')
    axes[0].plot(x, y_a, 'r-', lw=5, alpha=0.6, label='alternative distribution')

    axes[0].set_ylabel('Density', fontsize=16)
    axes[0].set_xlabel('Peak p-values', fontsize=16)
    axes[0].set_title('Distribution of {0} peak p-values'
                      '\n$\pi_1$={1:0.03f}'.format(len(p_values), pi1),
                      fontsize=20)

    legend = axes[0].legend(frameon=True, fontsize=14)
    frame = legend.get_frame()
    frame.set_facecolor('white')
    frame.set_edgecolor('black')

    axes[0].set_xlim((0, 1))

    # Z-values
    y, _, _ = axes[1].hist(z_values, bins=np.arange(min(z_values), 30, 0.3),
                            alpha=0.6, label='observed distribution')
    x_min, x_max = np.floor(np.min(z_values)), np.ceil(np.max(z_values))
    y_max = np.ceil(y.max())

    x = np.linspace(x_min, x_max, 100)
    y_0 = (1 - pi1) * nulPDF(x, exc=z_u, method=method)
    y_a = pi1*altPDF(x, mu=mu, sigma=sigma, exc=z_u, method=method)
    y_m = mixPDF(x, pi1=pi1, mu=mu, sigma=sigma, exc=z_u, method=method)

    axes[1].plot(x, y_a, 'r-', lw=5, alpha=0.6, label='alternative distribution')
    axes[1].plot(x, y_0, 'g-', lw=5, alpha=0.6, label='null distribution')
    axes[1].plot(x, y_m, 'b-', lw=5, alpha=0.6, label='total distribution')

    axes[1].set_title('Distribution of peak heights\n$\delta_1$ '
                      '= {0:0.03f}'.format(mu_s),
                      fontsize=20)
    axes[1].set_xlabel('Peak heights (z-values)', fontsize=16)
    axes[1].set_ylabel('Density', fontsize=16)

    legend = axes[1].legend(frameon=True, fontsize=14)
    frame = legend.get_frame()
    frame.set_facecolor('white')
    frame.set_edgecolor('black')

    axes[1].set_xlim((min(z_values), x_max))
    axes[1].set_ylim((0, y_max))

    return fig, axes
