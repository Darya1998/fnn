import numpy as np
import warnings

import scipy
from scipy.linalg import hankel, orthogonal_procrustes
from scipy.signal import periodogram, argrelextrema, savgol_filter
from scipy.spatial.distance import pdist, squareform, directed_hausdorff
from scipy.spatial import procrustes

import matplotlib.pyplot as plt

###------------------------------------###
#
#
#       Loading and featurizing data
#
#
###------------------------------------###

def hankel_matrix(data, q, p=None):
    """
    Find the Hankel matrix dimensionwise for multiple multidimensional 
    time series
    
    Arguments
    data : [N, T, 1] or [N, T, D] ndarray
        A collection of N time series of length T and dimensionality D
    q : int
        The width of the matrix (the number of features)
    p : int
        The height of the matrix (the number of samples)
    
    """
    
    if len(data.shape) == 3:
        return np.stack([_hankel_matrix(item, q, p) for item in data])
    
    if len(data.shape) == 1:
        data = data[:, None]
    return _hankel_matrix(data, q, p)  
    

def _hankel_matrix(data, q, p=None):
    """
    Calculate the hankel matrix of a multivariate timeseries
    
    data : array
        T x D multidimensional time series
    """
    if len(data.shape) == 1:
        data = data[:, None]

    # Hankel parameters
    if not p:
        p = len(data) - q
    all_hmats = list()
    for row in data.T:
        first, last = row[-(p + q) : -p], row[-p - 1 :]
        out = hankel(first, last)
        all_hmats.append(out)
    out = np.dstack(all_hmats)
    return np.transpose(out, (1, 0, 2))[:-1]


def train_test(dataset, sample_size, time_window, std=1.0, split=0.5):
    """
    Given a raw 1D time series, perform a standard rescale, and then find the 
    hankel matrix for the train and test partitions. The 

    dataset : ndarray, a 1D time series
    sample_size : int, the length of the train series
    std : float, the number of standard deviations by which to rescale
    split : float, the relative split between test/train
    """
    n = len(dataset)
    n_split = int((split/(1-split))*sample_size)

    assert n > sample_size + n_split, "Not enough data to make complete split"
    
    hm_train = hankel_matrix(dataset, time_window, p=sample_size)#[np.newaxis, ...].T
    hm_test = hankel_matrix(dataset[:(n_split+time_window)], time_window, p=sample_size)#[np.newaxis, ...].T

    mn_train, std_train = np.mean(hm_train), np.std(hm_train)
    
    X_train, X_test = [(item - mn_train)/(std*std_train) for item in (hm_train, hm_test)]
    
    return X_train, X_test

def standardize_ts(a, scale=1.0):
    """
    Standardize a T x D time series along its first dimension
    For dimensions with zero variance, divide by one instead of zero
    """
    stds = np.std(a, axis=0, keepdims=True)
    stds[stds==0] = 1
    return (a - np.mean(a, axis=0, keepdims=True))/(scale*stds)

def arff_to_data(path, fmt_spec=1):
    """
    Given a path to an arff file, load the file and convert it
    into a data matrix and labels
    Assumes that the structure of the arff file is the same as that used 
    by the UCR time series database:
    http://www.timeseriesclassification.com/
    
    Parameters
    - path : str
        The path of an .arff file
    - fmt_spec : int
        T he nesting level of the arff file. Different files have
        different nesting types; this must determined by trial-and-error
    
    Returns
    - data_rp : ndarray with shape (num_samples, num_timepoints, dimensions)
    """
    data, meta = arff.loadarff(path)
    y = [item[-1] for item in data]
    
    if fmt_spec == 0:
        data_rp = np.array([[tpt for tpt in sample][:-1] for sample in data]).astype(float)
    elif fmt_spec == 1:
        data_r = np.array([item[0] for item in data])
        data_rp = np.array([[[float(timepoint) for timepoint in component] for component in trial] for trial in data_r])
    else:
        warnings.warn("Format specification not implemented, falling back to fmt_spec=0")
        data_rp = np.array([[tpt for tpt in sample][:-1] for sample in data]).astype(float)
        data_rp = data_rp.T
    
    # Pad singleton for univariate time series
    if len(data_rp.shape) == 2:
        data_rp = data_rp[:, None, :]
     
    data_rp = np.transpose(data_rp, (0, 2, 1)) # use (N, T, D) format
    
    return data_rp, y


###------------------------------------###
#
#
#       Plotting and visualization
#
#
###------------------------------------###


def fixed_aspect_ratio(ratio):
    '''
    Set a fixed aspect ratio on matplotlib plots regardless of axis units
    '''
    xvals, yvals = plt.gca().axes.get_xlim(), plt.gca().axes.get_ylim()
    xrange = xvals[1]-xvals[0]
    yrange = yvals[1]-yvals[0]
    plt.gca().set_aspect(ratio*(xrange/yrange), adjustable='box')
    
def plot3dproj(x, y, z, *args, color=(0,0,0), shadow_dist=1.0, color_proj=None, 
    elev_azim=(39,-47), show_labels=False, **kwargs):
    """
    Create a three dimensional plot, with projections onto the 2D coordinate
    planes
    
    Parameters
    ----------
    x, y, z : 1D arrays of coordinates to plot
    *args : arguments passed to the matplotlib plt.plot functions
    - color : length-3 tuple
        The RGB color (with each element in [0,1]) to use for the
        three dimensional line plot
    - color_proj : length-3 tuple
        The RGB color (with each element in [0,1]) to use for the
        two dimensional projection plots. Defaults to a lighter version of the 
        plotting color
    - shadow_dist : float
        The relative distance of axes to their shadow. If a single value, 
        then the same distance is used for all three axies. If a triple, then 
        different values are used for all axes
    - elev_azim : length-2 tuple
        The starting values of elevation and azimuth when viewing the figure
    - show_labels : bool
        Whether to show numerical labels on the axes
    """

    if not color_proj:
        color_proj = lighter(color, .6)

    if np.isscalar(shadow_dist) == 1:
        sdist_x = shadow_dist
        sdist_y = shadow_dist
        sdist_z = shadow_dist
    else:
        sdist_x, sdist_y, sdist_z = shadow_dist

    fig = plt.figure(figsize=(7,7))
    ax = fig.add_subplot(111, projection= '3d')
    
    ax.plot(x, z, *args, zdir='y', zs=sdist_y*np.max(y), color=color_proj, **kwargs)
    ax.plot(y, z, *args, zdir='x', zs=sdist_x*np.min(x), color=color_proj, **kwargs)
    ax.plot(x, y, *args, zdir='z', zs=sdist_z*np.min(z), color=color_proj, **kwargs)
    ax.plot(x, y, z, *args, color=color, **kwargs)

    ax.view_init(elev=elev_azim[0], azim=elev_azim[1])
    ax.set_aspect('auto', adjustable='box') 
    
#     ratio = 1.0
#     xvals, yvals = ax.get_xlim(), ax.get_ylim()
#     xrange = xvals[1]-xvals[0]
#     yrange = yvals[1]-yvals[0]
#     ax.set_aspect(ratio*(xrange/yrange), adjustable='box')
    fixed_aspect_ratio(1.0)

    if not show_labels:
        ax.set_xticklabels([])                               
        ax.set_yticklabels([])                               
        ax.set_zticklabels([])
    #plt.show()

    return ax

def lighter(clr, f=1/3):
    """
    An implementation of Mathematica's Lighter[] 
    function for RGB colors
    clr : 3-tuple or list, an RGB color
    f : float, the fraction by which to brighten
    """
    gaps = [f*(1 - val) for val in clr]
    new_clr = [val + gap for gap, val in zip(gaps, clr)]
    return new_clr